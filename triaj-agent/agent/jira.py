"""Integrarea Jira, in ambele directii.

    Jira ──(webhook sau polling JQL)──> agent ──(comentariu + prioritate + etichete)──> Jira
                                          │
                       aprobare umana ────┘──(comentariu cu decizia omului)──> Jira

- Intrare: webhook-ul `POST /webhooks/jira` (Jira trimite la fiecare issue creat) SAU polling
  periodic cu JQL (util cand Jira Cloud nu poate ajunge la un laptop din spatele unui NAT).
- Idempotent: o cheie Jira (ex. ITSM-42) se clasifica o singura data, oricate webhook-uri sau
  sincronizari vin pentru ea.
- Iesire: dupa clasificare si dupa decizia omului, agentul scrie inapoi in issue: un comentariu
  cu decizia si motivarea, prioritatea Jira si etichete (triaj-ai, triaj-auto / triaj-review,
  echipa-...). Fiecare actiune e logata in `jira_events` (ok sau eroare), deci se vede ce s-a
  trimis si ce a esuat.
- Fara credentiale (JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN goale) totul merge in MOD SIMULARE:
  fluxul ruleaza identic, dar actiunile spre Jira doar se inregistreaza local, marcate „simulare”.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

from agent import db

log = logging.getLogger("jira")

# P1..P4 <-> numele standard de prioritate din Jira
PRIORITY_TO_JIRA = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}
JIRA_TO_PRIORITY = {"highest": "P1", "blocker": "P1", "critical": "P1", "high": "P2", "major": "P2",
                    "medium": "P3", "low": "P4", "lowest": "P4", "minor": "P4", "trivial": "P4"}
LABEL_ALL = "triaj-ai"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jira_links (
    ticket_id   INTEGER PRIMARY KEY,
    jira_key    TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL,          -- webhook | polling | demo
    created_at  TEXT NOT NULL,
    last_sync   TEXT,
    sync_status TEXT,                   -- ok | partial | error | simulated
    last_error  TEXT
);
CREATE TABLE IF NOT EXISTS jira_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    ticket_id  INTEGER,
    jira_key   TEXT,
    direction  TEXT NOT NULL,           -- in | out
    action     TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    simulated  INTEGER NOT NULL,
    detail     TEXT
);
"""


# ════════════════════════════════════════════════════════════════
# Configurare
# ════════════════════════════════════════════════════════════════

def settings() -> dict:
    """Citita la fiecare apel, ca .env-ul sa poata fi schimbat fara rebuild de cod."""
    project = os.environ.get("JIRA_PROJECT_KEY", "").strip()
    # atentie: in JQL `labels != x` exclude si issue-urile fara nicio eticheta, de aici `is EMPTY`
    default_jql = (f'project = "{project}" AND created >= -1d '
                   f'AND (labels is EMPTY OR labels != {LABEL_ALL}) ORDER BY created ASC' if project else "")
    return {
        "base_url": os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/"),
        "email": os.environ.get("JIRA_EMAIL", "").strip(),
        "token": os.environ.get("JIRA_API_TOKEN", "").strip(),
        "project": project,
        "jql": os.environ.get("JIRA_JQL", "").strip() or default_jql,
        "poll_seconds": int(os.environ.get("JIRA_POLL_SECONDS", "0") or 0),
        "writeback": os.environ.get("JIRA_WRITEBACK", "true").lower() == "true",
        "set_priority": os.environ.get("JIRA_SET_PRIORITY", "true").lower() == "true",
        "webhook_secret": os.environ.get("JIRA_WEBHOOK_SECRET", "").strip(),
    }


def is_live() -> bool:
    s = settings()
    return bool(s["base_url"] and s["email"] and s["token"])


# ════════════════════════════════════════════════════════════════
# Baza de date
# ════════════════════════════════════════════════════════════════

def _ensure_schema():
    with db.conn() as c:
        c.executescript(SCHEMA)


def link_for_key(jira_key: str) -> dict | None:
    _ensure_schema()
    r = db.query("SELECT * FROM jira_links WHERE jira_key = ?", (jira_key,))
    return r[0] if r else None


def link_for_ticket(ticket_id: int) -> dict | None:
    _ensure_schema()
    r = db.query("SELECT * FROM jira_links WHERE ticket_id = ?", (ticket_id,))
    return r[0] if r else None


def _save_link(ticket_id: int, jira_key: str, source: str):
    _ensure_schema()
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO jira_links (ticket_id, jira_key, source, created_at) VALUES (?, ?, ?, ?)",
                  (ticket_id, jira_key, source, db.now()))


def _update_link(ticket_id: int, status: str, error: str | None = None):
    with db.conn() as c:
        c.execute("UPDATE jira_links SET last_sync = ?, sync_status = ?, last_error = ? WHERE ticket_id = ?",
                  (db.now(), status, error, ticket_id))


def log_event(ticket_id: int | None, jira_key: str | None, direction: str, action: str,
              ok: bool, simulated: bool, **detail):
    _ensure_schema()
    with db.conn() as c:
        c.execute("""INSERT INTO jira_events (at, ticket_id, jira_key, direction, action, ok, simulated, detail)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (db.now(), ticket_id, jira_key, direction, action, int(ok), int(simulated),
                   json.dumps(detail, ensure_ascii=False, default=str)))


def events(limit: int = 50) -> list[dict]:
    _ensure_schema()
    rows = db.query("SELECT * FROM jira_events ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "{}")
        r["ok"], r["simulated"] = bool(r["ok"]), bool(r["simulated"])
        r["ticket_code"] = db.code(r["ticket_id"]) if r["ticket_id"] else None
    return rows


def linked_tickets(limit: int = 50) -> list[dict]:
    _ensure_schema()
    return db.query("""SELECT l.*, t.status, t.priority, t.final_priority, t.team, t.final_team,
                              t.category, t.confidence, t.decision_rule
                       FROM jira_links l JOIN tickets t ON t.id = l.ticket_id
                       ORDER BY l.ticket_id DESC LIMIT ?""", (limit,))


# ════════════════════════════════════════════════════════════════
# Parsare issue Jira -> text de tichet
# ════════════════════════════════════════════════════════════════

def adf_to_text(node: Any) -> str:
    """Jira Cloud (API v3) trimite descrierea ca Atlassian Document Format; webhook-urile si
    Jira Server o trimit ca text simplu. Accepta ambele."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(t for t in (adf_to_text(n) for n in node) if t)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return adf_to_text(node.get("content"))
    return str(node)


def issue_to_ticket(issue: dict) -> dict:
    f = issue.get("fields") or {}
    summary = (f.get("summary") or "").strip()
    description = re.sub(r"\s+", " ", adf_to_text(f.get("description"))).strip()
    text = ". ".join(p.rstrip(".") for p in (summary, description) if p)
    reporter = (f.get("reporter") or {}).get("displayName") or "jira"
    jira_priority = (f.get("priority") or {}).get("name")
    return {"key": issue.get("key", ""), "text": text, "reporter": reporter,
            "jira_priority": jira_priority, "issue_type": (f.get("issuetype") or {}).get("name")}


def verify_signature(raw_body: bytes, signature_header: str | None, token_param: str | None) -> bool:
    """Daca JIRA_WEBHOOK_SECRET e setat: accepta semnatura HMAC trimisa de Jira Cloud
    (header X-Hub-Signature: sha256=...) sau ?token=<secret> in URL. Altfel, accepta orice."""
    secret = settings()["webhook_secret"]
    if not secret:
        return True
    if token_param and hmac.compare_digest(token_param, secret):
        return True
    if signature_header and "=" in signature_header:
        algo, sig = signature_header.split("=", 1)
        if algo.lower() == "sha256":
            expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(sig, expected)
    return False


# ════════════════════════════════════════════════════════════════
# Client HTTP Jira (REST v3 Cloud, cu fallback v2 pentru Server/Data Center)
# ════════════════════════════════════════════════════════════════

class JiraError(RuntimeError):
    pass


def _request(method: str, path: str, **kw) -> Any:
    s = settings()
    try:
        r = requests.request(method, f"{s['base_url']}{path}", auth=(s["email"], s["token"]),
                             headers={"Accept": "application/json", "Content-Type": "application/json"},
                             timeout=kw.pop("timeout", 15), **kw)
    except requests.RequestException as e:
        raise JiraError(f"Jira nu raspunde: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        try:
            body = r.json()
            msg = "; ".join(body.get("errorMessages", [])) or json.dumps(body.get("errors", {}))
        except ValueError:
            msg = r.text[:200]
        raise JiraError(f"HTTP {r.status_code}: {msg or r.reason}")
    return r.json() if r.content else None


def test_connection() -> dict:
    if not is_live():
        return {"ok": False, "mode": "simulare",
                "message": "Lipsesc JIRA_BASE_URL, JIRA_EMAIL sau JIRA_API_TOKEN in .env."}
    try:
        me = _request("GET", "/rest/api/3/myself")
        return {"ok": True, "mode": "live", "message": f"Conectat ca {me.get('displayName')}",
                "account": me.get("emailAddress") or me.get("displayName")}
    except JiraError as e:
        return {"ok": False, "mode": "live", "message": str(e)}


def search(jql: str, max_results: int = 25) -> list[dict]:
    fields = ["summary", "description", "priority", "reporter", "issuetype", "labels"]
    try:  # Jira Cloud (endpoint-ul nou; /rest/api/3/search a fost retras)
        r = _request("POST", "/rest/api/3/search/jql",
                     data=json.dumps({"jql": jql, "maxResults": max_results, "fields": fields}))
    except JiraError as e:
        if "HTTP 404" not in str(e):
            raise
        r = _request("POST", "/rest/api/2/search",  # Jira Server / Data Center
                     data=json.dumps({"jql": jql, "maxResults": max_results, "fields": fields}))
    return r.get("issues", [])


def _adf(paragraphs: list[str]) -> dict:
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs if p]}


# ════════════════════════════════════════════════════════════════
# Ce scriem inapoi in Jira
# ════════════════════════════════════════════════════════════════

def _team_label(team: str | None) -> str | None:
    return f"echipa-{re.sub(r'[^a-z0-9]+', '-', team.lower()).strip('-')}" if team else None


def build_writeback(ticket: dict, event: str) -> dict:
    """Ce trebuie schimbat in issue-ul Jira, ca structura neutra (testabila fara retea)."""
    code = ticket["code"]
    priority = ticket.get("final_priority") or ticket.get("priority")
    team = ticket.get("final_team") or ticket.get("team")
    conf = ticket.get("confidence")
    conf_txt = f"{conf:.0%}" if isinstance(conf, (int, float)) else "—"
    status = ticket["status"]

    if event == "classified":
        if status == "auto_routed":
            head = f"[Agent de triaj] {code}: rutat AUTOMAT catre {team} cu prioritatea {priority}."
            state_label = "triaj-auto"
        elif status == "duplicate":
            head = f"[Agent de triaj] {code}: duplicat al unui tichet existent — {ticket.get('decision_reason', '')}"
            state_label = "triaj-duplicat"
        else:
            head = (f"[Agent de triaj] {code}: propunere {priority} / {team} — ASTEAPTA aprobarea unui om. "
                    f"Motiv: {ticket.get('decision_reason') or '—'}")
            state_label = "triaj-review"
        lines = [head,
                 f"Categorie: {ticket.get('category') or '—'} · Siguranta agentului: {conf_txt}",
                 f"Motivare: {ticket.get('reasoning') or '—'}"]
        if ticket.get("citations"):
            lines.append("Precedente folosite: " + ", ".join(ticket["citations"]))
    else:  # reviewed
        who = ticket.get("reviewed_by") or "un responsabil"
        if status == "approved":
            changed = []
            if ticket.get("final_priority") != ticket.get("priority"):
                changed.append(f"prioritate {ticket.get('priority')} → {ticket.get('final_priority')}")
            if ticket.get("final_team") != ticket.get("team"):
                changed.append(f"echipa {ticket.get('team')} → {ticket.get('final_team')}")
            head = f"[Agent de triaj] {code}: APROBAT de {who} — {priority} / {team}."
            if changed:
                head += " Corectii fata de propunerea agentului: " + "; ".join(changed) + "."
            state_label = "triaj-aprobat"
        else:
            head = f"[Agent de triaj] {code}: RESPINS de {who} — trimis la triaj manual (Service Desk)."
            state_label = "triaj-manual"
        lines = [head]
        if ticket.get("review_note"):
            lines.append(f"Comentariul omului: {ticket['review_note']}")

    add = [LABEL_ALL, state_label]
    if status in ("auto_routed", "approved"):
        add.append(_team_label(team))
    remove = [lbl for lbl in ("triaj-review", "triaj-auto") if lbl != state_label]
    return {
        "comment": lines,
        "labels_add": [lbl for lbl in add if lbl],
        "labels_remove": remove,
        "priority": PRIORITY_TO_JIRA.get(priority) if status in ("auto_routed", "approved") else None,
    }


def push(ticket_id: int, event: str) -> dict:
    """Scrie in Jira rezultatul (dupa clasificare sau dupa decizia omului). Nu arunca exceptii:
    fiecare actiune e logata separat; o prioritate care nu se poate seta nu blocheaza comentariul."""
    link = link_for_ticket(ticket_id)
    if link is None:
        return {"skipped": "tichetul nu vine din Jira"}
    s = settings()
    ticket = db.get_ticket(ticket_id)
    key = link["jira_key"]
    plan = build_writeback(ticket, event)

    if not s["writeback"]:
        log_event(ticket_id, key, "out", "writeback_dezactivat", True, not is_live(), event=event)
        return {"skipped": "JIRA_WRITEBACK=false"}

    if not is_live():
        log_event(ticket_id, key, "out", f"comentariu ({event})", True, True, text=plan["comment"])
        log_event(ticket_id, key, "out", "etichete", True, True, add=plan["labels_add"], remove=plan["labels_remove"])
        if plan["priority"]:
            log_event(ticket_id, key, "out", "prioritate", True, True, value=plan["priority"])
        _update_link(ticket_id, "simulated")
        return {"mode": "simulare", "plan": plan}

    errors = []
    try:
        _request("POST", f"/rest/api/3/issue/{key}/comment", data=json.dumps({"body": _adf(plan["comment"])}))
        log_event(ticket_id, key, "out", f"comentariu ({event})", True, False, text=plan["comment"])
    except JiraError as e:
        errors.append(f"comentariu: {e}")
        log_event(ticket_id, key, "out", f"comentariu ({event})", False, False, error=str(e))

    label_ops = [{"add": lbl} for lbl in plan["labels_add"]] + [{"remove": lbl} for lbl in plan["labels_remove"]]
    try:
        _request("PUT", f"/rest/api/3/issue/{key}", data=json.dumps({"update": {"labels": label_ops}}))
        log_event(ticket_id, key, "out", "etichete", True, False, add=plan["labels_add"], remove=plan["labels_remove"])
    except JiraError as e:
        errors.append(f"etichete: {e}")
        log_event(ticket_id, key, "out", "etichete", False, False, error=str(e))

    if plan["priority"] and s["set_priority"]:
        try:
            _request("PUT", f"/rest/api/3/issue/{key}",
                     data=json.dumps({"fields": {"priority": {"name": plan["priority"]}}}))
            log_event(ticket_id, key, "out", "prioritate", True, False, value=plan["priority"])
        except JiraError as e:  # des: campul priority nu e pe ecranul de editare al proiectului
            errors.append(f"prioritate: {e}")
            log_event(ticket_id, key, "out", "prioritate", False, False, error=str(e))

    _update_link(ticket_id, "ok" if not errors else ("error" if len(errors) >= 2 else "partial"),
                 "; ".join(errors) or None)
    return {"mode": "live", "plan": plan, "errors": errors}


# ════════════════════════════════════════════════════════════════
# Intrare: un issue Jira -> tichet clasificat (idempotent)
# ════════════════════════════════════════════════════════════════

_ingest_lock = threading.Lock()


def ingest(issue: dict, source: str, submit) -> dict:
    """`submit(text, submitted_by)` e service.submit_ticket (injectat, ca modulul sa nu depinda
    circular de service). Intoarce {"created": bool, "ticket_id", "jira_key", "result"}."""
    parsed = issue_to_ticket(issue)
    key = parsed["key"]
    if not key:
        raise ValueError("Issue-ul Jira nu are cheie (issue.key).")
    if len(parsed["text"]) < 5:
        raise ValueError("Issue-ul Jira nu are suficient text (summary + description).")

    with _ingest_lock:  # webhook si polling pot sosi simultan pentru acelasi issue
        existing = link_for_key(key)
        if existing:
            log_event(existing["ticket_id"], key, "in", f"ignorat: deja procesat ({source})", True, not is_live())
            return {"created": False, "ticket_id": existing["ticket_id"], "jira_key": key, "result": None}
        result = submit(parsed["text"], f"jira:{parsed['reporter']}")
        tid = result["ticket"]["id"]
        _save_link(tid, key, source)

    db.audit(tid, f"jira-{source}", "ingested_from_jira", jira_key=key,
             jira_priority=parsed["jira_priority"], jira_type=parsed["issue_type"])
    log_event(tid, key, "in", f"issue primit ({source})", True, not is_live(),
              summary=parsed["text"][:140], jira_priority=parsed["jira_priority"])
    return {"created": True, "ticket_id": tid, "jira_key": key, "result": result}


# ════════════════════════════════════════════════════════════════
# Polling (sincronizare periodica)
# ════════════════════════════════════════════════════════════════

_poll_state = {"running": False, "last_run": None, "last_result": None, "thread": None}
_stop = threading.Event()


def sync_once(submit) -> dict:
    """Cauta issue-uri noi cu JQL si le trece prin agent. Folosit de polling si de butonul
    „Sincronizeaza acum”."""
    s = settings()
    if not is_live():
        return {"ok": False, "mode": "simulare", "message": "Jira nu e configurat — polling indisponibil.",
                "found": 0, "created": 0}
    if not s["jql"]:
        return {"ok": False, "mode": "live", "message": "Seteaza JIRA_PROJECT_KEY sau JIRA_JQL.",
                "found": 0, "created": 0}
    try:
        issues = search(s["jql"])
    except JiraError as e:
        log_event(None, None, "in", "polling esuat", False, False, error=str(e))
        out = {"ok": False, "mode": "live", "message": str(e), "found": 0, "created": 0}
        _poll_state.update(last_run=db.now(), last_result=out)
        return out
    created, failed = [], []
    for issue in issues:
        try:
            r = ingest(issue, "polling", submit)
            if r["created"]:
                created.append(r)
                push(r["ticket_id"], "classified")
        except Exception as e:  # un issue stricat nu opreste restul
            failed.append(issue.get("key"))
            log_event(None, issue.get("key"), "in", "issue ignorat", False, False, error=str(e))
    out = {"ok": True, "mode": "live", "found": len(issues), "created": len(created),
           "keys": [r["jira_key"] for r in created], "failed": failed,
           "message": f"{len(issues)} issue-uri gasite, {len(created)} noi clasificate."}
    _poll_state.update(last_run=db.now(), last_result=out)
    return out


def start_polling(submit):
    s = settings()
    if s["poll_seconds"] <= 0 or not is_live() or _poll_state["running"]:
        return False
    interval = max(15, s["poll_seconds"])
    _stop.clear()

    def loop():
        log.info("Polling Jira pornit: la fiecare %ss, JQL: %s", interval, s["jql"])
        while not _stop.is_set():
            try:
                sync_once(submit)
            except Exception:
                log.exception("Polling Jira: eroare neasteptata")
            _stop.wait(interval)
        _poll_state["running"] = False

    t = threading.Thread(target=loop, name="jira-poller", daemon=True)
    _poll_state.update(running=True, thread=t)
    t.start()
    return True


def stop_polling():
    _stop.set()


def status() -> dict:
    s = settings()
    _ensure_schema()
    counts = db.query("""SELECT COUNT(*) n,
                                SUM(sync_status = 'ok') ok, SUM(sync_status IN ('error', 'partial')) err
                         FROM jira_links""")[0]
    return {
        "mode": "live" if is_live() else "simulare",
        "base_url": s["base_url"] or None,
        "project": s["project"] or None,
        "jql": s["jql"] or None,
        "writeback": s["writeback"],
        "set_priority": s["set_priority"],
        "webhook_secret_set": bool(s["webhook_secret"]),
        "polling": {"enabled": s["poll_seconds"] > 0, "interval_s": s["poll_seconds"] or None,
                    "running": _poll_state["running"], "last_run": _poll_state["last_run"],
                    "last_result": _poll_state["last_result"]},
        "linked_tickets": counts["n"] or 0,
        "sync_ok": counts["ok"] or 0,
        "sync_errors": counts["err"] or 0,
    }
