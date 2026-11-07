"""Integrarea Jira, fara retea: in teste nu exista credentiale, deci ruleaza in MOD SIMULARE
(actiunile spre Jira se logheaza local). Verificam fluxul complet: intrare -> clasificare ->
scriere inapoi -> decizie umana -> scriere inapoi, plus idempotenta si securitatea webhook-ului."""

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from agent import jira
from api.main import app
from tests.conftest import label


def issue(key, summary, description="", priority="Medium"):
    return {"webhookEvent": "jira:issue_created",
            "issue": {"key": key, "fields": {"summary": summary, "description": description,
                                              "priority": {"name": priority},
                                              "reporter": {"displayName": "Ana Pop"},
                                              "issuetype": {"name": "Incident"}}}}


def test_auto_routed_ticket_is_written_back(fake_llm):
    with TestClient(app) as c:
        fake_llm([label("P4", "Hardware", "Desktop Support", 0.92)])
        r = c.post("/webhooks/jira", json=issue("ITSM-501", "Mouse wireless nu mai merge la birou B2"))
        assert r.status_code == 201
        body = r.json()
        assert body["created"] is True and body["ticket"]["status"] == "auto_routed"

        detail = c.get(f"/tickets/{body['ticket']['id']}").json()
        assert detail["jira"]["jira_key"] == "ITSM-501"
        assert detail["jira"]["sync_status"] == "simulated"
        actions = {e["action"]: e for e in detail["jira"]["events"]}
        assert "comentariu (classified)" in actions
        assert "AUTOMAT" in actions["comentariu (classified)"]["detail"]["text"][0]
        assert actions["prioritate"]["detail"]["value"] == "Low"          # P4 -> Low
        assert "echipa-desktop-support" in actions["etichete"]["detail"]["add"]
        assert all(e["simulated"] for e in detail["jira"]["events"])


def test_same_jira_key_is_classified_once(fake_llm):
    with TestClient(app) as c:
        fake_llm([label("P3", "Software", "Application Support", 0.88)])
        first = c.post("/webhooks/jira", json=issue("ITSM-502", "Excel se inchide la deschiderea rapoartelor"))
        # Jira reincearca webhook-ul: nu trebuie un al doilea apel LLM sau un al doilea tichet
        second = c.post("/webhooks/jira", json=issue("ITSM-502", "Excel se inchide la deschiderea rapoartelor"))
        assert second.status_code == 201
        assert second.json()["created"] is False
        assert second.json()["ticket"]["id"] == first.json()["ticket"]["id"]


def test_human_decision_reaches_jira(fake_llm):
    with TestClient(app) as c:
        fake_llm([label("P1", "Security", "SecOps", 0.97)])
        t = c.post("/webhooks/jira", json=issue("ITSM-503", "Ransomware pe serverul de fisiere",
                                                "Fisierele au extensia .locked", "Highest")).json()["ticket"]
        assert t["status"] == "pending_approval"        # P1 -> mereu la om

        r = c.post(f"/tickets/{t['id']}/review",
                   json={"approved": True, "reviewer": "mario", "team": "Infrastructure", "note": "infra izoleaza"})
        assert r.status_code == 200
        ev = c.get(f"/tickets/{t['id']}").json()["jira"]["events"]
        reviewed = [e for e in ev if e["action"] == "comentariu (reviewed)"]
        assert reviewed and "APROBAT de mario" in reviewed[0]["detail"]["text"][0]
        assert "echipa SecOps → Infrastructure" in reviewed[0]["detail"]["text"][0]


def test_tickets_not_from_jira_are_not_pushed(fake_llm):
    with TestClient(app) as c:
        fake_llm([label("P3", "Network", "Network", 0.9)])
        t = c.post("/tickets", json={"text": "Wi-Fi lent la etajul 3"}).json()["ticket"]
        assert c.get(f"/tickets/{t['id']}").json()["jira"] is None
        assert c.post(f"/integrations/jira/push/{t['id']}").json() == {"skipped": "tichetul nu vine din Jira"}


def test_status_and_events_endpoints(fake_llm):
    with TestClient(app) as c:
        s = c.get("/integrations/jira/status").json()
        assert s["mode"] == "simulare" and s["polling"]["enabled"] is False
        assert c.post("/integrations/jira/test").json()["ok"] is False
        sync = c.post("/integrations/jira/sync").json()
        assert sync["ok"] is False and sync["mode"] == "simulare"
        assert isinstance(c.get("/integrations/jira/events").json(), list)


def test_irrelevant_events_are_ignored():
    with TestClient(app) as c:
        r = c.post("/webhooks/jira", json={"webhookEvent": "comment_created", "issue": {"key": "X-1"}})
        assert r.json() == {"source": "jira", "ignored": "comment_created"}


def test_webhook_secret(monkeypatch, fake_llm):
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "s3cret")
    payload = json.dumps(issue("ITSM-504", "Imprimanta de la receptie nu printeaza")).encode()
    with TestClient(app) as c:
        assert c.post("/webhooks/jira", content=payload).status_code == 401
        sig = "sha256=" + hmac.new(b"s3cret", payload, hashlib.sha256).hexdigest()
        fake_llm([label("P4", "Hardware", "Desktop Support", 0.9)])
        assert c.post("/webhooks/jira", content=payload, headers={"X-Hub-Signature": sig}).status_code == 201
        assert c.post("/webhooks/jira?token=s3cret", content=payload).status_code == 201   # idempotent


def test_adf_description_is_flattened():
    adf = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "VPN-ul cade"},
                                          {"type": "text", "text": "la fiecare 20 de minute."}]}]}
    t = jira.issue_to_ticket({"key": "A-1", "fields": {"summary": "VPN instabil", "description": adf}})
    assert t["text"] == "VPN instabil. VPN-ul cade la fiecare 20 de minute"


def test_rejected_ticket_writeback_plan():
    plan = jira.build_writeback({"code": "INC-0009", "status": "rejected", "priority": "P2", "team": "Network",
                                 "reviewed_by": "ana", "review_note": "nu e retea"}, "reviewed")
    assert "RESPINS de ana" in plan["comment"][0]
    assert plan["priority"] is None                     # nu atingem prioritatea cand omul respinge
    assert "triaj-manual" in plan["labels_add"] and "triaj-review" in plan["labels_remove"]


class FakeJira:
    """Inlocuieste requests.request: raspunde ca Jira Cloud si retine ce i s-a trimis."""
    def __init__(self, issues=(), fail_priority=False):
        self.calls, self.issues, self.fail_priority = [], list(issues), fail_priority

    def __call__(self, method, url, **kw):
        import requests
        body = json.loads(kw.get("data") or "null")
        self.calls.append((method, url.split(".net", 1)[1], body))
        r = requests.Response()
        r.status_code, payload = 200, {}
        if url.endswith("/myself"):
            payload = {"displayName": "Bot Triaj", "emailAddress": "bot@firma.ro"}
        elif url.endswith("/search/jql"):
            payload = {"issues": self.issues}
        elif url.endswith("/comment"):
            r.status_code, payload = 201, {"id": "1"}
        elif method == "PUT" and self.fail_priority and "priority" in (body or {}).get("fields", {}):
            r.status_code, payload = 400, {"errors": {"priority": "Field 'priority' cannot be set."}}
        elif method == "PUT":
            r.status_code = 204
        r._content = json.dumps(payload).encode() if r.status_code != 204 else b""
        return r


def _live(monkeypatch, fake):
    monkeypatch.setenv("JIRA_BASE_URL", "https://firma.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "bot@firma.ro")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "ITSM")
    monkeypatch.setattr(jira.requests, "request", fake)


def test_live_polling_classifies_and_writes_back(monkeypatch, fake_llm):
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Nu merge."}]}]}
    fake = FakeJira(issues=[{"key": "ITSM-77", "fields": {"summary": "Outlook nu sincronizeaza mailurile",
                                                          "description": adf, "priority": {"name": "Medium"},
                                                          "reporter": {"displayName": "Ion"}}}])
    _live(monkeypatch, fake)
    with TestClient(app) as c:
        assert c.post("/integrations/jira/test").json()["message"] == "Conectat ca Bot Triaj"
        fake_llm([label("P3", "Email/Communication", "Messaging", 0.91)])
        r = c.post("/integrations/jira/sync").json()
        assert r["ok"] and r["created"] == 1 and r["keys"] == ["ITSM-77"]
        assert c.post("/integrations/jira/sync").json()["created"] == 0      # a doua oara: nimic nou

    paths = [(m, p) for m, p, _ in fake.calls]
    assert ("POST", "/rest/api/3/issue/ITSM-77/comment") in paths
    comment = next(b for m, p, b in fake.calls if p.endswith("/comment"))
    assert comment["body"]["type"] == "doc"                                   # format ADF
    labels = next(b for m, p, b in fake.calls if m == "PUT" and "update" in b)
    assert {"add": "triaj-ai"} in labels["update"]["labels"]
    prio = next(b for m, p, b in fake.calls if m == "PUT" and "fields" in b)
    assert prio == {"fields": {"priority": {"name": "Medium"}}}
    jql = next(b for m, p, b in fake.calls if p.endswith("/search/jql"))["jql"]
    assert 'project = "ITSM"' in jql and "labels is EMPTY" in jql


def test_live_partial_failure_is_reported(monkeypatch, fake_llm):
    fake = FakeJira(fail_priority=True)
    _live(monkeypatch, fake)
    with TestClient(app) as c:
        fake_llm([label("P4", "Hardware", "Desktop Support", 0.93)])
        t = c.post("/webhooks/jira", json=issue("ITSM-78", "Keyboard keys stuck on accounting workstation", "Several keys do not respond, need a replacement keyboard")).json()
        assert t["ticket"]["status"] == "auto_routed"
        link = c.get(f"/tickets/{t['ticket']['id']}").json()["jira"]
        assert link["sync_status"] == "partial"                      # comentariul si etichetele au mers
        assert "prioritate" in link["last_error"]
        failed = [e for e in link["events"] if not e["ok"]]
        assert [e["action"] for e in failed] == ["prioritate"]
