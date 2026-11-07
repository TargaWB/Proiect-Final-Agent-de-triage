"""Orchestrarea agentului ca graf LangGraph. Fiecare nod are un singur rol; starea
(TriageState) e tot ce trece de la un nod la altul (handoff).

  check_previous --duplicat--> handle_duplicate --> END
        |
        +--> retrieve --> classify --> decide --> execute --> END
        (RAG)       (LLM + Pydantic)  (guardrail)  (tool-uri deterministe)
"""

import re
import time
from typing import List, Optional, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, StateGraph

from agent import db, retrieval
from agent.config import OUT_OF_SCOPE_DISTANCE, WEAK_MATCH_DISTANCE, CATEGORY_TO_TEAM
from agent.classifier import ClassificationResult, classify
from agent.router import decide as guardrail, is_safety_hazard
from agent.schemas import Decision
from agent.telemetry import span
from agent.tools import assign_to_queue, link_duplicate, request_human_approval


class TriageState(TypedDict, total=False):
    ticket_id: int
    text: str
    force_new: bool
    duplicate: Optional[dict]
    previous: List[dict]
    similar: List[Document]
    result: Optional[ClassificationResult]
    out_of_scope: bool
    weak_match: bool
    decision: Optional[Decision]
    executed: Optional[str]
    started: float


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def check_previous(state: TriageState) -> TriageState:
    """Rol: detectie de duplicate. Cauta in tichetele trimise anterior (RAG pe tichetele trimise)."""
    duplicate, previous, norm = None, [], normalize(state["text"])
    for doc in retrieval.submitted_retriever.invoke(state["text"]):
        t = db.get_ticket(doc.metadata["ticket_id"])
        if not t or t["id"] == state["ticket_id"]:
            continue
        t["distance"] = doc.metadata["distance"]
        usable = t["status"] != "rejected" and t["priority"]
        if duplicate is None and usable and not state.get("force_new") and normalize(t["text"]) == norm:
            duplicate = t
        else:
            previous.append(t)
    return {"duplicate": duplicate, "previous": previous}


def handle_duplicate(state: TriageState) -> TriageState:
    """Rol: refolosire. Acelasi tichet -> aceeasi clasificare, fara apel LLM (0 tokeni)."""
    o, tid = state["duplicate"], state["ticket_id"]
    msg = link_duplicate.invoke({"ticket_id": tid, "original_id": o["id"]})
    db.update_ticket(
        tid, status="duplicate", duplicate_of=o["id"],
        priority=o.get("final_priority") or o["priority"], category=o["category"],
        team=o.get("final_team") or o["team"], confidence=o["confidence"], reasoning=o["reasoning"],
        citations=o["citations"], decision_rule="duplicate",
        decision_reason=f"Identic cu {o['code']} — clasificare refolosită, fără apel LLM.",
        latency_ms=round((time.perf_counter() - state["started"]) * 1000, 1),
    )
    return {"executed": msg}


def retrieve(state: TriageState) -> TriageState:
    """Rol: retriever. Precedente istorice = context + exemple few-shot + citari."""
    similar = retrieval.history_retriever.invoke(state["text"])
    top1 = min((d.metadata["distance"] for d in similar), default=1.0)
    return {"similar": similar, "out_of_scope": top1 > OUT_OF_SCOPE_DISTANCE,
            "weak_match": WEAK_MATCH_DISTANCE < top1 <= OUT_OF_SCOPE_DISTANCE}


def classify_node(state: TriageState) -> TriageState:
    """Rol: clasificator (singurul pas cu LLM). Propune, nu executa."""
    if state.get("out_of_scope"):   # filtru de relevanta: fara apel LLM, 0 tokeni
        return {"result": ClassificationResult(classification=None, error="out_of_scope")}
    r = classify(state["text"], state["similar"], state.get("previous", []))
    for u in r.usages:
        db.add_usage(state["ticket_id"], u)
    # Pericol fizic (foc, fum, scantei) -> fortam P1, indiferent ce a propus LLM-ul.
    # Nu e o cale separata de escaladare: P1 trece oricum prin p1_always_human mai
    # jos, deci regula ramane "doar P1 sau confidence sub prag escaladeaza".
    if r.classification and is_safety_hazard(state["text"]) and r.classification.priority != "P1":
        original = r.classification.priority
        r.classification = r.classification.model_copy(update={
            "priority": "P1",
            "reasoning": f"[Prioritate forțată la P1: text indică pericol fizic] {r.classification.reasoning}",
        })
        r.error = f"priority_overridden_safety (era {original})"
    return {"result": r}


def decide(state: TriageState) -> TriageState:
    """Rol: guardrail. Reguli fixe, fara LLM."""
    r = state["result"]
    c = r.classification
    with span("guardrail", "GUARDRAIL", **{
        "input.value": c.model_dump_json() if c else "null",
        "ticket.id": db.code(state["ticket_id"]),
    }) as s:
        d = guardrail(c, r.llm_unavailable, state.get("out_of_scope", False),
                     state.get("weak_match", False), similar_docs=state.get("similar"))
        s.set_attribute("output.value", d.model_dump_json())
        s.set_attribute("guardrail.rule", d.rule)
        s.set_attribute("guardrail.status", d.status)
    return {"decision": d}


def execute(state: TriageState) -> TriageState:
    """Rol: executor. Singurul loc unde se schimba starea sistemului, doar prin tool-uri."""
    tid, r, d = state["ticket_id"], state["result"], state["decision"]
    c = r.classification
    fields = dict(decision_rule=d.rule, decision_reason=d.reason, model=f"{r.provider}:{r.model}",
                  attempts=r.attempts, latency_ms=round((time.perf_counter() - state["started"]) * 1000, 1))
    correct_team = None
    if c:
        correct_team = CATEGORY_TO_TEAM.get(c.category, c.suggested_team)
        reasoning = c.reasoning
        if correct_team != c.suggested_team:
            reasoning += (f" Echipă corectată automat din '{c.suggested_team}' la '{correct_team}' "
                          f"(pe baza categoriei {c.category}).")
        fields.update(priority=c.priority, category=c.category, team=correct_team,
                      confidence=c.confidence, reasoning=reasoning, citations=c.citations)
    else:
        fields.update(reasoning=r.error if r.llm_unavailable else f"Ieșire invalidă după {r.attempts} încercări: {r.error}")
    db.update_ticket(tid, **fields)

    if d.status == "auto_routed":
        msg = assign_to_queue.invoke({"ticket_id": tid, "team": correct_team,
                                      "priority": c.priority, "executed_by": "agent"})
        db.update_ticket(tid, status="auto_routed", final_priority=c.priority, final_team=correct_team)
    else:
        msg = request_human_approval.invoke({"ticket_id": tid, "rule": d.rule, "reason": d.reason})
    retrieval.index_submitted(db.get_ticket(tid))
    return {"executed": msg}


def _after_previous(state: TriageState) -> str:
    return "handle_duplicate" if state.get("duplicate") else "retrieve"


def build_graph():
    g = StateGraph(TriageState)
    g.add_node("check_previous", check_previous)
    g.add_node("handle_duplicate", handle_duplicate)
    g.add_node("retrieve", retrieve)
    g.add_node("classify", classify_node)
    g.add_node("decide", decide)
    g.add_node("execute", execute)
    g.set_entry_point("check_previous")
    g.add_conditional_edges("check_previous", _after_previous, ["handle_duplicate", "retrieve"])
    g.add_edge("handle_duplicate", END)
    g.add_edge("retrieve", "classify")
    g.add_edge("classify", "decide")
    g.add_edge("decide", "execute")
    g.add_edge("execute", END)
    return g.compile()


triage_graph = build_graph()