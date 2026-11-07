"""Operatiile de nivel inalt folosite de API: trimitere tichet, aprobare umana, KPI, FinOps."""

import json
import os
import statistics
import time
from datetime import datetime

from openinference.instrumentation import using_session, using_user

from agent import db, retrieval
from agent.config import EVAL_DIR, TEAMS
from agent.graph import triage_graph
from agent.telemetry import current_trace_id, span
from agent.tools import assign_to_queue, send_to_manual_triage


class ReviewError(ValueError):
    pass


def submit_ticket(text: str, submitted_by: str | None = None, force_new: bool = False) -> dict:
    retrieval.ensure_index()
    tid = db.create_ticket(text.strip(), submitted_by)
    db.audit(tid, submitted_by or "anonim", "submitted")
    code = db.code(tid)
    with using_session(code), using_user(submitted_by or "anonim"):
        with span("triage_ticket", "AGENT", **{"input.value": text, "ticket.id": code}) as s:
            state = triage_graph.invoke({"ticket_id": tid, "text": text.strip(),
                                         "force_new": force_new, "started": time.perf_counter()},
                                        config={"run_name": "triage_graph"})
            t = db.get_ticket(tid)
            s.set_attribute("output.value", json.dumps({k: t[k] for k in
                            ("status", "priority", "category", "team", "confidence", "decision_rule")}))
            db.update_ticket(tid, trace_id=current_trace_id())
    return {
        "ticket": db.get_ticket(tid),
        "duplicate_of": state.get("duplicate"),
        "previous": state.get("previous", []),
        "similar": [{"id": d.metadata["id"], "subject": d.metadata["subject"], "priority": d.metadata["priority"],
                     "category": d.metadata["category"], "team": d.metadata["team"],
                     "distance": d.metadata["distance"], "resolution": d.metadata.get("resolution", "")}
                    for d in state.get("similar", [])],
    }


def review_ticket(ticket_id: int, approved: bool, reviewer: str, note: str = "",
                  priority: str | None = None, team: str | None = None) -> dict:
    t = db.get_ticket(ticket_id)
    if t is None:
        raise ReviewError("Tichet inexistent.")
    if t["status"] != "pending_approval":
        raise ReviewError(f"{t['code']} nu e în așteptare (status: {t['status']}).")
    final_priority, final_team = priority or t["priority"], team or t["team"]
    if approved and (final_priority is None or final_team not in TEAMS):
        raise ReviewError("Alege prioritatea și echipa înainte de aprobare.")

    overrides = {k: v for k, v in (("priority", (t["priority"], final_priority)), ("team", (t["team"], final_team)))
                 if approved and v[0] != v[1]}
    with using_session(t["code"]), using_user(reviewer):
        with span("human_review", "CHAIN", **{
            "ticket.id": t["code"], "review.reviewer": reviewer,
            "review.decision": "approved" if approved else "rejected", "review.note": note,
            "review.overrides": overrides or None,
            "input.value": json.dumps({"proposed_priority": t["priority"], "proposed_team": t["team"],
                                       "rule": t["decision_rule"]}),
        }):
            if approved:
                assign_to_queue.invoke({"ticket_id": ticket_id, "team": final_team,
                                        "priority": final_priority, "executed_by": f"human:{reviewer}"})
                status = "approved"
            else:
                send_to_manual_triage.invoke({"ticket_id": ticket_id, "reviewer": reviewer, "note": note})
                status = "rejected"
    db.update_ticket(ticket_id, status=status, reviewed_by=reviewer, reviewed_at=db.now(), review_note=note,
                     final_priority=final_priority if approved else None, final_team=final_team if approved else None)
    db.audit(ticket_id, f"human:{reviewer}", status, note=note, overrides=overrides)
    return db.get_ticket(ticket_id)


def ticket_detail(ticket_id: int) -> dict | None:
    t = db.get_ticket(ticket_id)
    if t is None:
        return None
    from agent import jira  # import local: jira e optional si nu trebuie sa incarce la importul service
    link = jira.link_for_ticket(ticket_id)
    return {**t, "assignments": db.assignments_for(ticket_id), "audit": db.audit_for(ticket_id),
            "usage": db.query("SELECT * FROM llm_usage WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
            "jira": {**link, "events": [e for e in jira.events(200) if e["ticket_id"] == ticket_id]}
            if link else None}


# ---------------- KPI live (din baza de date) ----------------

def _hours_between(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600


def kpis() -> dict:
    rows = db.query("SELECT * FROM tickets WHERE status != 'received'")
    classified = [r for r in rows if r["status"] != "duplicate"]
    reviewed = [r for r in classified if r["status"] in ("approved", "rejected")]
    escalated = [r for r in classified if r["decision_rule"] != "auto"]
    overridden = [r for r in reviewed if r["status"] == "rejected"
                  or r["final_priority"] != r["priority"] or r["final_team"] != r["team"]]
    lat = [r["latency_ms"] for r in classified if r["latency_ms"]]
    route_h = ([r["latency_ms"] / 3_600_000 for r in classified if r["status"] == "auto_routed" and r["latency_ms"]]
               + [_hours_between(r["created_at"], r["reviewed_at"]) for r in reviewed if r["reviewed_at"]])
    n = len(classified)
    pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    return {
        "tickets_total": len(rows),
        "classified": n,
        "duplicates": len(rows) - n,
        "by_status": {s: sum(r["status"] == s for r in rows) for s in
                      ("auto_routed", "pending_approval", "approved", "rejected", "duplicate")},
        "by_rule": {rule: sum(r["decision_rule"] == rule for r in rows)
                    for rule in sorted({r["decision_rule"] for r in rows if r["decision_rule"]})},
        "auto_resolution_rate_pct": pct(sum(r["status"] == "auto_routed" for r in classified), n),
        "human_intervention_pct": pct(len(escalated), n),
        "human_override_pct": pct(len(overridden), len(reviewed)),
        "agent_latency_ms_p50": round(statistics.median(lat), 1) if lat else None,
        "agent_latency_ms_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1) if lat else None,
        "mean_time_to_route_hours": round(statistics.mean(route_h), 5) if route_h else None,
    }


def finops() -> dict:
    u = db.query("""SELECT provider, model, COUNT(*) calls, SUM(prompt_tokens) p, SUM(completion_tokens) c,
                           SUM(cost_usd) cost, AVG(latency_ms) lat,
                           SUM(purpose = 'classify_retry') retries
                    FROM llm_usage GROUP BY provider, model""")
    per_ticket = db.query("""SELECT ticket_id, SUM(prompt_tokens + completion_tokens) tok, SUM(cost_usd) cost
                             FROM llm_usage WHERE ticket_id IS NOT NULL GROUP BY ticket_id""")
    dup = db.query("SELECT COUNT(*) n FROM tickets WHERE status = 'duplicate'")[0]["n"]
    avg_tok = statistics.mean([r["tok"] for r in per_ticket]) if per_ticket else 0
    avg_cost = statistics.mean([r["cost"] for r in per_ticket]) if per_ticket else 0
    total_cost = sum((r["cost"] or 0) for r in u)
    return {
        "by_model": u,
        "llm_calls": sum(r["calls"] for r in u),
        "prompt_tokens": sum(r["p"] or 0 for r in u),
        "completion_tokens": sum(r["c"] or 0 for r in u),
        "retries": sum(r["retries"] or 0 for r in u),
        "cost_usd_equivalent": round(total_cost, 6),
        "cost_usd_actual": 0.0,
        "avg_tokens_per_ticket": round(avg_tok, 1),
        "avg_cost_per_ticket_usd": round(avg_cost, 8),
        "projected_cost_per_1000_tickets_usd": round(avg_cost * 1000, 4),
        "duplicates_served_from_cache": dup,
        "tokens_saved_by_cache": round(dup * avg_tok),
    }


def evaluation_results() -> dict:
    out = {}
    for name in ("classification", "ragas", "kpi_simulation"):
        path = os.path.join(EVAL_DIR, f"{name}_latest.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[name] = json.load(f)
    return out
