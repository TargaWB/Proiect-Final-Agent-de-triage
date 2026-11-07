"""Helpers partajate intre paginile Streamlit. Fara emoji — badge-urile sunt in theme.py."""

from datetime import datetime

from theme import priority_badge, status_badge, rule_badge  # noqa: F401  — re-export


RULE_LABEL = {
    "auto": "Risc scazut — directionat automat",
    "p1_always_human": "P1 — trimis la om",
    "low_confidence": "Confidence mic — trimis la om",
    "unknown_team": "Echipa necunoscuta — trimis la om",
    "team_category_mismatch": "Echipa nu corespunde categoriei — trimis la om",
    "out_of_scope": "In afara domeniului IT — verificare umana",
    "weak_match": "Potrivire slaba cu precedentele — verificare umana",
    "invalid_output": "Iesire invalida — triaj manual",
    "llm_unavailable": "LLM indisponibil — triaj manual",
    "duplicate": "Duplicat (fara LLM)",
}


def when(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def badge_text(t):
    """Text scurt de prioritate (fara HTML) — pentru tabelele dataframe."""
    p = t.get("final_priority") or t.get("priority")
    return p or "—"


def status_text(status):
    """Text scurt de status (fara HTML) — pentru tabelele dataframe."""
    labels = {
        "received": "Primit",
        "auto_routed": "Rutat automat",
        "pending_approval": "In asteptare",
        "approved": "Aprobat",
        "rejected": "Respins",
        "duplicate": "Duplicat",
    }
    return labels.get(status, status)


def short(text, n=110):
    return text if len(text) <= n else text[:n].rstrip() + "…"
