"""Execution layer: singurele functii care schimba starea sistemului. Deterministe, cu
validari, expuse ca tool-uri LangChain (apar ca spanuri TOOL in Phoenix = "ce s-a executat").
LLM-ul nu le apeleaza niciodata direct; le apeleaza graful, dupa decizie sau aprobare."""

from typing import Literal

from langchain_core.tools import tool

from agent import db
from agent.config import TEAMS

MANUAL_QUEUE = "Service Desk (triaj manual)"


def _require(ticket_id: int, allowed: tuple):
    t = db.get_ticket(ticket_id)
    if t is None:
        raise ValueError(f"Tichetul {ticket_id} nu exista.")
    if t["status"] not in allowed:
        raise ValueError(f"{t['code']} are status {t['status']}; actiunea cere {allowed}.")
    return t


@tool
def assign_to_queue(ticket_id: int, team: str, priority: Literal["P1", "P2", "P3", "P4"], executed_by: str) -> str:
    """Ruteaza tichetul in coada echipei. Valideaza echipa si starea tichetului."""
    if team not in TEAMS:
        raise ValueError(f"Echipa necunoscuta: {team}")
    _require(ticket_id, ("received", "pending_approval"))
    db.add_assignment(ticket_id, team, priority, executed_by)
    db.audit(ticket_id, executed_by, "assigned", queue=team, priority=priority)
    return f"{db.code(ticket_id)} -> {team} ({priority})"


@tool
def request_human_approval(ticket_id: int, rule: str, reason: str) -> str:
    """Pune tichetul in coada de aprobare umana."""
    _require(ticket_id, ("received",))
    db.update_ticket(ticket_id, status="pending_approval")
    db.audit(ticket_id, "agent", "approval_requested", rule=rule, reason=reason)
    return f"{db.code(ticket_id)} in asteptare: {rule}"


@tool
def link_duplicate(ticket_id: int, original_id: int) -> str:
    """Marcheaza tichetul ca duplicat al unui tichet existent (fara apel LLM)."""
    _require(ticket_id, ("received",))
    if db.get_ticket(original_id) is None:
        raise ValueError(f"Tichetul original {original_id} nu exista.")
    db.audit(ticket_id, "agent", "linked_duplicate", original=db.code(original_id))
    return f"{db.code(ticket_id)} duplicat al {db.code(original_id)}"


@tool
def send_to_manual_triage(ticket_id: int, reviewer: str, note: str = "") -> str:
    """Tichet respins de om: merge in coada de triaj manual."""
    _require(ticket_id, ("pending_approval",))
    db.add_assignment(ticket_id, MANUAL_QUEUE, None, f"human:{reviewer}")
    db.audit(ticket_id, f"human:{reviewer}", "sent_to_manual_triage", note=note)
    return f"{db.code(ticket_id)} -> {MANUAL_QUEUE}"
