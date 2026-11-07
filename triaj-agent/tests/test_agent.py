import pytest
from pydantic import ValidationError

from agent import db, service
from agent.router import decide
from agent.schemas import TicketClassification
from tests.conftest import label


def tc(**kw):
    base = dict(priority="P3", category="Network", suggested_team="Network", confidence=0.9, reasoning="ok ok")
    return TicketClassification(**{**base, **kw})


# ---------------- validare (Pydantic) ----------------

def test_schema_rejects_unknown_priority_and_category():
    with pytest.raises(ValidationError):
        tc(priority="P9")
    with pytest.raises(ValidationError):
        tc(category="Printers")
    with pytest.raises(ValidationError):
        tc(confidence=1.4)


# ---------------- guardrail ----------------

@pytest.mark.parametrize("c, rule, status", [
    (None, "invalid_output", "pending_approval"),
    (dict(priority="P1", confidence=0.99), "p1_always_human", "pending_approval"),
    (dict(confidence=0.69), "low_confidence", "pending_approval"),
    (dict(confidence=0.70), "auto", "auto_routed"),           # exact pe prag -> automat
    (dict(suggested_team="DBA"), "auto", "auto_routed"),      # echipa se corecteaza in graph, nu escaladeaza
])
def test_guardrail_rules(c, rule, status):
    d = decide(None if c is None else tc(**c))
    assert (d.rule, d.status) == (rule, status)


# ---------------- flux complet ----------------

def test_auto_routed_ticket_is_executed_and_logged(fake_llm):
    fake_llm([label("P4", "Hardware", "Desktop Support", 0.9)])
    t = service.submit_ticket("Imprimanta de la etajul 3 nu printeaza", "ana")["ticket"]
    assert t["status"] == "auto_routed" and t["final_team"] == "Desktop Support"
    detail = service.ticket_detail(t["id"])
    assert [a["executed_by"] for a in detail["assignments"]] == ["agent"]
    assert [e["event"] for e in detail["audit"]] == ["submitted", "assigned"]
    assert detail["usage"][0]["prompt_tokens"] == 900


def test_duplicate_reuses_classification_without_llm(fake_llm):
    fake_llm([label("P2", "Software", "Application Support", 0.9)])
    first = service.submit_ticket("Excel se inchide singur cand deschid fisierul de buget")["ticket"]
    fake_llm([])  # orice apel LLM ar esua
    r = service.submit_ticket("Excel se inchide singur cand deschid fisierul de buget.")
    assert r["ticket"]["status"] == "duplicate" and r["ticket"]["duplicate_of"] == first["id"]
    assert service.ticket_detail(r["ticket"]["id"])["usage"] == []


def test_near_identical_but_different_incident_is_not_merged(fake_llm):
    fake_llm([label("P4", "Hardware", "Desktop Support", 0.9)])
    service.submit_ticket("Imprimanta de la etajul 2 nu printeaza deloc")
    fake_llm([label("P4", "Hardware", "Desktop Support", 0.9)])
    r = service.submit_ticket("Imprimanta de la etajul 5 nu printeaza deloc")
    assert r["ticket"]["status"] != "duplicate"      # alt etaj = alt incident
    assert r["previous"]                              # dar e aratat ca exemplu


def test_similar_ticket_is_shown_as_previous(fake_llm):
    fake_llm([label("P3", "Email/Communication", "Messaging", 0.9)])
    service.submit_ticket("Outlook nu mai sincronizeaza emailurile pe laptop de azi dimineata")
    fake_llm([label("P3", "Email/Communication", "Messaging", 0.9)])
    r = service.submit_ticket("De dimineata Outlook-ul de pe laptop nu isi mai aduce mesajele noi")
    assert r["ticket"]["status"] == "auto_routed"
    assert r["previous"] and r["previous"][0]["code"].startswith("INC-")


def test_invalid_output_retries_then_goes_to_manual_triage(fake_llm):
    fake_llm(["nu e json", '{"priority": "P9"}'])
    t = service.submit_ticket("ceva ciudat se intampla")["ticket"]
    assert (t["status"], t["decision_rule"], t["attempts"]) == ("pending_approval", "invalid_output", 2)
    with pytest.raises(service.ReviewError):
        service.review_ticket(t["id"], True, "mario")          # fara prioritate/echipa
    t = service.review_ticket(t["id"], True, "mario", priority="P4", team="Desktop Support")
    assert t["status"] == "approved" and t["final_team"] == "Desktop Support"


def test_llm_failure_does_not_lose_the_ticket(monkeypatch):
    import agent.classifier as classifier

    class Down:
        def invoke(self, *a, **k):
            raise ConnectionError("Groq 401 / timeout")
    monkeypatch.setattr(classifier, "get_chat_model", lambda *a, **k: Down())
    t = service.submit_ticket("Serverul de fisiere nu raspunde")["ticket"]
    assert (t["status"], t["decision_rule"]) == ("pending_approval", "llm_unavailable")
    assert "LLM indisponibil" in t["reasoning"]


def test_human_review_approve_with_override_and_reject(fake_llm):
    fake_llm([label("P3", "Access/Permissions", "Identity & Access", 0.5)])   # sub prag -> om
    a = service.submit_ticket("Contul meu e blocat dupa schimbarea parolei")["ticket"]
    assert a["decision_rule"] == "low_confidence"
    a = service.review_ticket(a["id"], True, "mario", "corectat", team="Identity & Access")
    assert a["final_team"] == "Identity & Access"
    assert service.ticket_detail(a["id"])["assignments"][-1]["executed_by"] == "human:mario"

    fake_llm([label("P3", "Network", "Network", 0.4)])
    b = service.submit_ticket("internetul merge cam greu uneori")["ticket"]
    b = service.review_ticket(b["id"], False, "mario", "prea vag")
    assert b["status"] == "rejected"
    with pytest.raises(service.ReviewError):
        service.review_ticket(b["id"], True, "mario")          # nu se poate aproba de doua ori


def test_kpis_and_finops_are_computed(fake_llm):
    fake_llm([label("P3", "Network", "Network", 0.9)])
    service.submit_ticket("VPN-ul se deconecteaza la fiecare 10 minute")
    k, f = service.kpis(), service.finops()
    assert k["classified"] >= 1 and 0 <= k["auto_resolution_rate_pct"] <= 100
    assert f["llm_calls"] >= 1 and f["cost_usd_equivalent"] > 0 and f["cost_usd_actual"] == 0


# ---------------- observabilitate ----------------

def test_trace_contains_retrieval_llm_guardrail_tool_and_review(fake_llm, spans):
    fake_llm([label("P1", "Cloud/Infrastructure", "Infrastructure", 0.95)])
    t = service.submit_ticket("Tot clusterul de productie din cloud e cazut", "ana")["ticket"]
    service.review_ticket(t["id"], True, "mario", "confirmat")

    got = spans.get_finished_spans()
    kinds = {s.name: s.attributes.get("openinference.span.kind") for s in got}
    assert kinds["HistoryRetriever"] == "RETRIEVER"
    assert kinds["llm_classify"] == "LLM"
    assert kinds["guardrail"] == "GUARDRAIL"
    assert kinds["request_human_approval"] == "TOOL" and kinds["assign_to_queue"] == "TOOL"
    # toate spanurile tichetului sunt in aceeasi sesiune Phoenix
    assert {s.attributes.get("session.id") for s in got} == {t["code"]}
    review = next(s for s in got if s.name == "human_review")
    assert review.attributes["review.reviewer"] == "mario"
    assert review.attributes["user.id"] == "mario"
    by_id = {s.context.span_id: s for s in got}
    guard = next(s for s in got if s.name == "guardrail")
    assert by_id[guard.parent.span_id].name == "decide"          # guardrail-ul e sub nodul "decide"
    llm = next(s for s in got if s.name == "llm_classify")
    assert llm.attributes["llm.token_count.prompt"] == 900
    assert db.get_ticket(t["id"])["trace_id"]