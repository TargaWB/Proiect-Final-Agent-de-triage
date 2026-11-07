from fastapi.testclient import TestClient

from api.main import app
from tests.conftest import label


def test_api_end_to_end(fake_llm):
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/config").json()["confidence_threshold"] == 0.7

        fake_llm([label("P1", "Security", "SecOps", 0.95)])
        r = client.post("/tickets", json={"text": "Ransomware pe statia de la contabilitate", "submitted_by": "ana"})
        assert r.status_code == 201
        t = r.json()["ticket"]
        assert t["status"] == "pending_approval"
        assert any(p["id"] == t["id"] for p in client.get("/approvals").json())

        assert client.post(f"/tickets/{t['id']}/review", json={"approved": True, "reviewer": ""}).status_code == 422
        r = client.post(f"/tickets/{t['id']}/review", json={"approved": True, "reviewer": "mario"})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert client.post(f"/tickets/{t['id']}/review", json={"approved": True, "reviewer": "mario"}).status_code == 409
        assert client.get("/tickets/99999").status_code == 404

        detail = client.get(f"/tickets/{t['id']}").json()
        assert detail["assignments"][0]["executed_by"] == "human:mario"

        k = client.get("/kpis").json()
        assert {"live", "finops", "evaluation"} <= k.keys()
        assert client.post("/tickets", json={"text": "x"}).status_code == 422


def test_jira_webhook(fake_llm):
    """Webhook-ul Jira creeaza un tichet si il clasifica."""
    with TestClient(app) as client:
        fake_llm([label("P3", "Hardware", "Desktop Support", 0.85)])
        payload = {
            "webhookEvent": "jira:issue_created",
            "issue": {
                "key": "ITSM-999",
                "fields": {
                    "summary": "Monitor flickering on workstation B204",
                    "description": "The 27-inch Dell monitor flickers every few seconds.",
                    "priority": {"name": "Medium"},
                    "reporter": {"displayName": "Test User"},
                    "issuetype": {"name": "Incident"},
                }
            }
        }
        r = client.post("/webhooks/jira", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["source"] == "jira"
        assert data["jira_key"] == "ITSM-999"
        assert data["ticket"]["priority"] == "P3"


def test_jira_webhook_rejects_empty():
    """Webhook-ul respinge un tichet Jira fara text."""
    with TestClient(app) as client:
        payload = {
            "webhookEvent": "jira:issue_created",
            "issue": {"key": "X-1", "fields": {"summary": "", "description": ""}}
        }
        r = client.post("/webhooks/jira", json=payload)
        assert r.status_code == 400


def test_db_info():
    """Endpoint-ul /db/info returneaza informatii corecte."""
    with TestClient(app) as client:
        r = client.get("/db/info")
        assert r.status_code == 200
        data = r.json()
        assert "tickets_total" in data
        assert "index_docs" in data
        assert "db_path" in data


def test_retention_dry_run(fake_llm):
    """Retentia in modul dry_run nu sterge nimic."""
    with TestClient(app) as client:
        fake_llm([label("P4", "Software", "Application Support", 0.9)])
        client.post("/tickets", json={"text": "Test ticket for retention dry run check"})

        r = client.post("/maintenance/retention", json={"dry_run": True})
        assert r.status_code == 200
        data = r.json()
        assert data["dry_run"] is True
        assert "action" in data
