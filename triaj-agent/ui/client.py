"""Clientul HTTP al interfetei. UI-ul nu importa nimic din agent: trece totul prin API."""

import os

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
PHOENIX_UI_URL = os.environ.get("PHOENIX_UI_URL", "http://localhost:6006").rstrip("/")
APPROVALS_UI_URL = os.environ.get("APPROVALS_UI_URL", "http://localhost:8502").rstrip("/")


class APIError(Exception):
    pass


def _call(method, path, **kw):
    try:
        r = requests.request(method, f"{API_URL}{path}", timeout=kw.pop("timeout", 60), **kw)
    except requests.ConnectionError:
        raise APIError(f"API-ul nu răspunde la {API_URL}. Pornește-l (uvicorn sau docker compose).")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        raise APIError(detail if isinstance(detail, str) else str(detail))
    return r.json()


def config():
    return _call("GET", "/config")


def submit(text, submitted_by=None, force_new=False):
    return _call("POST", "/tickets", json={"text": text, "submitted_by": submitted_by or None,
                                           "force_new": force_new}, timeout=120)


def tickets(limit=15):
    return _call("GET", "/tickets", params={"limit": limit})


def ticket(ticket_id):
    return _call("GET", f"/tickets/{ticket_id}")


def approvals():
    return _call("GET", "/approvals")


def review(ticket_id, approved, reviewer, note="", priority=None, team=None):
    return _call("POST", f"/tickets/{ticket_id}/review", json={
        "approved": approved, "reviewer": reviewer, "note": note, "priority": priority, "team": team})


def kpis():
    return _call("GET", "/kpis")


def rebuild_index():
    return _call("POST", "/index/rebuild", timeout=300)


def db_info():
    return _call("GET", "/db/info")


def jira_webhook(payload):
    return _call("POST", "/webhooks/jira", json=payload, timeout=120)


def jira_status():
    return _call("GET", "/integrations/jira/status")


def jira_test():
    return _call("POST", "/integrations/jira/test", timeout=30)


def jira_sync():
    return _call("POST", "/integrations/jira/sync", timeout=300)


def jira_events(limit=40):
    return _call("GET", "/integrations/jira/events", params={"limit": limit})


def jira_tickets(limit=40):
    return _call("GET", "/integrations/jira/tickets", params={"limit": limit})


def jira_push(ticket_id):
    return _call("POST", f"/integrations/jira/push/{ticket_id}", timeout=60)


def run_retention(archive_after_days=90, purge_after_days=365, dry_run=True):
    return _call("POST", "/maintenance/retention", json={
        "archive_after_days": archive_after_days,
        "purge_after_days": purge_after_days,
        "dry_run": dry_run,
    }, timeout=120)
