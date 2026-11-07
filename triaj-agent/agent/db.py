"""SQLite: sursa de adevar pentru tichete, decizii, executii, consum LLM si audit.
Indexul Chroma se poate reconstrui oricand din aceste tabele."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from agent.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    text            TEXT NOT NULL,
    submitted_by    TEXT,
    status          TEXT NOT NULL,
    priority        TEXT,
    category        TEXT,
    team            TEXT,
    confidence      REAL,
    reasoning       TEXT,
    citations       TEXT DEFAULT '[]',
    decision_rule   TEXT,
    decision_reason TEXT,
    duplicate_of    INTEGER,
    model           TEXT,
    attempts        INTEGER DEFAULT 0,
    latency_ms      REAL,
    final_priority  TEXT,
    final_team      TEXT,
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    review_note     TEXT,
    trace_id        TEXT
);
CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL,
    at          TEXT NOT NULL,
    queue       TEXT NOT NULL,
    priority    TEXT,
    executed_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id         INTEGER,
    at                TEXT NOT NULL,
    provider          TEXT,
    model             TEXT,
    purpose           TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        REAL,
    cost_usd          REAL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    at        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    event     TEXT NOT NULL,
    details   TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def code(ticket_id: int) -> str:
    return f"INC-{ticket_id:04d}"


@contextmanager
def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _ticket(r):
    if r is None:
        return None
    d = dict(r)
    d["citations"] = json.loads(d.get("citations") or "[]")
    d["code"] = code(d["id"])
    return d


# ---------------- tichete ----------------

def create_ticket(text: str, submitted_by: str | None) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO tickets (created_at, text, submitted_by, status) VALUES (?, ?, ?, 'received')",
                        (now(), text, submitted_by))
        return cur.lastrowid


def update_ticket(ticket_id: int, **fields):
    if "citations" in fields:
        fields["citations"] = json.dumps(fields["citations"])
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE tickets SET {cols} WHERE id = ?", (*fields.values(), ticket_id))


def get_ticket(ticket_id: int):
    with conn() as c:
        return _ticket(c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())


def list_tickets(status: str | None = None, limit: int = 50):
    q, args = "SELECT * FROM tickets", []
    if status:
        q, args = q + " WHERE status = ?", [status]
    with conn() as c:
        return [_ticket(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()]


def pending_queue():
    """P1 primele, apoi cele mai nesigure."""
    with conn() as c:
        rows = c.execute("""SELECT * FROM tickets WHERE status = 'pending_approval'
                            ORDER BY CASE priority WHEN 'P1' THEN 0 ELSE 1 END,
                                     COALESCE(confidence, 0) ASC, id ASC""").fetchall()
    return [_ticket(r) for r in rows]


def indexable_tickets():
    with conn() as c:
        rows = c.execute("""SELECT * FROM tickets WHERE status NOT IN ('duplicate', 'received')
                            ORDER BY id""").fetchall()
    return [_ticket(r) for r in rows]


# ---------------- executii, consum, audit ----------------

def add_assignment(ticket_id: int, queue: str, priority: str | None, executed_by: str):
    with conn() as c:
        c.execute("INSERT INTO assignments (ticket_id, at, queue, priority, executed_by) VALUES (?, ?, ?, ?, ?)",
                  (ticket_id, now(), queue, priority, executed_by))


def assignments_for(ticket_id: int):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM assignments WHERE ticket_id = ? ORDER BY id",
                                           (ticket_id,)).fetchall()]


def add_usage(ticket_id: int | None, u):
    with conn() as c:
        c.execute("""INSERT INTO llm_usage (ticket_id, at, provider, model, purpose, prompt_tokens,
                        completion_tokens, latency_ms, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (ticket_id, now(), u.provider, u.model, u.purpose, u.prompt_tokens,
                   u.completion_tokens, u.latency_ms, u.cost_usd))


def audit(ticket_id: int | None, actor: str, event: str, **details):
    with conn() as c:
        c.execute("INSERT INTO audit_log (ticket_id, at, actor, event, details) VALUES (?, ?, ?, ?, ?)",
                  (ticket_id, now(), actor, event, json.dumps(details, ensure_ascii=False, default=str)))


def audit_for(ticket_id: int):
    with conn() as c:
        rows = c.execute("SELECT * FROM audit_log WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
    return [{**dict(r), "details": json.loads(r["details"] or "{}")} for r in rows]


def query(sql: str, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
