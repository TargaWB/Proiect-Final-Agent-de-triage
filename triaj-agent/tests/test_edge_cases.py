"""Edge case-uri pentru regulile finale: escaladeaza doar P1 si confidence < 70%.
Ruleaza: pytest tests/test_edge_cases.py -v   (fara retea, fara cheie Groq)."""

import pytest

from agent import retrieval, service
from agent.router import decide, is_safety_hazard
from agent.schemas import TicketClassification
from tests.conftest import label


def tc(**kw):
    base = dict(priority="P3", category="Network", suggested_team="Network", confidence=0.9, reasoning="ok ok")
    return TicketClassification(**{**base, **kw})


# ---------------- guardrail: praguri si ordine ----------------

@pytest.mark.parametrize("conf, rule", [
    (0.70, "auto"),            # exact pe prag -> automat ("sub 70%" = strict mai mic)
    (0.7001, "auto"),
    (0.6999, "low_confidence"),
    (0.0, "low_confidence"),
    (1.0, "auto"),
])
def test_confidence_boundary(conf, rule):
    assert decide(tc(confidence=conf)).rule == rule


def test_p1_wins_over_everything_even_at_full_confidence():
    assert decide(tc(priority="P1", confidence=1.0)).rule == "p1_always_human"
    assert decide(tc(priority="P1", confidence=0.1)).rule == "p1_always_human"   # P1 se verifica primul


def test_out_of_scope_and_llm_failures_always_go_to_human():
    assert decide(None, out_of_scope=True).rule == "out_of_scope"
    assert decide(tc(), out_of_scope=True).rule == "out_of_scope"      # chiar daca exista clasificare
    assert decide(None, llm_unavailable=True).rule == "llm_unavailable"
    assert decide(None).rule == "invalid_output"


def test_removed_rules_no_longer_escalate():
    # weak_match, echipa inconsistenta etc. nu mai blocheaza rutarea automata
    assert decide(tc(), weak_match=True).rule == "auto"
    assert decide(tc(suggested_team="DBA")).rule == "auto"
    assert decide(tc(suggested_team="Echipa inventata")).rule == "auto"


# ---------------- detectie pericol fizic ----------------

@pytest.mark.parametrize("text", [
    "Cablul la router scoate scantei",
    "Cablul scoate scântei",
    "Smoke coming from the UPS in the server room",
    "miros de ars din camera serverelor",
    "Laptop caught fire at the desk",
    "Fumul iese din rack-ul 3",
    "Laptopul se supraincalzeste si miroase urat",
    "Got an electric shock from the docking station",
    "Sparks coming out of the power strip",
])
def test_safety_hazard_detected(text):
    assert is_safety_hazard(text)


@pytest.mark.parametrize("text", [
    "Firewall blocks port 443",               # "fire" in "firewall"
    "Need to focus the camera on the whiteboard",   # "foc" in "focus"
    "Printer jams every few years",           # "ars" in "years"
    "Parser error when opening the Excel export",
    "Cannot burn a DVD with the new drive",
    "Imprimanta nu printeaza",
    "VPN-ul cade des",
    "",
])
def test_safety_hazard_no_false_positives(text):
    assert not is_safety_hazard(text)


# ---------------- schema: normalizare ----------------

@pytest.mark.parametrize("raw_priority, raw_category", [
    (" p1 ", "hardware"), ("P2.", "NETWORK "), ("p3", "email/communication"),
])
def test_schema_normalizes_case_and_whitespace(raw_priority, raw_category):
    c = tc(priority=raw_priority, category=raw_category)
    assert c.priority in {"P1", "P2", "P3", "P4"}
    assert c.category in {"Hardware", "Network", "Email/Communication"}


def test_schema_still_rejects_garbage():
    for bad in (dict(priority="urgent"), dict(priority="P5"), dict(category="Printers"), dict(category="")):
        with pytest.raises(Exception):
            tc(**bad)


# ---------------- flux complet ----------------

def test_physical_hazard_is_forced_to_p1_and_goes_to_human(fake_llm):
    fake_llm([label("P2", "Hardware", "Desktop Support", 0.95)])   # LLM-ul zice P2, sigur pe el
    t = service.submit_ticket("Cablul la router scoate scantei")["ticket"]
    assert t["priority"] == "P1"
    assert (t["status"], t["decision_rule"]) == ("pending_approval", "p1_always_human")
    assert "forțată la P1" in t["reasoning"]


def test_firewall_ticket_is_not_forced_to_p1(fake_llm):
    fake_llm([label("P3", "Network", "Network", 0.9)])
    t = service.submit_ticket("Firewall-ul blocheaza accesul la portul 443 din biroul de la etaj")["ticket"]
    assert t["priority"] == "P3"


def test_wrong_team_is_auto_corrected_from_category_without_escalation(fake_llm):
    fake_llm([label("P3", "Database", "Desktop Support", 0.9)])    # categorie corecta, echipa halucinata
    t = service.submit_ticket("Baza de date raspunde foarte greu la interogari")["ticket"]
    assert t["team"] == "DBA" and t["final_team"] == "DBA"
    assert t["status"] == "auto_routed"
    assert "Echipă corectată automat" in t["reasoning"]


def test_exactly_70_percent_routes_automatically(fake_llm):
    fake_llm([label("P3", "Network", "Network", 0.70)])
    t = service.submit_ticket("Routerul din biroul 4 are conexiune lenta de azi")["ticket"]
    assert (t["status"], t["decision_rule"]) == ("auto_routed", "auto")


def test_just_below_70_percent_goes_to_human(fake_llm):
    fake_llm([label("P3", "Network", "Network", 0.69)])
    t = service.submit_ticket("Routerul din biroul 5 are conexiune lenta de azi")["ticket"]
    assert (t["status"], t["decision_rule"]) == ("pending_approval", "low_confidence")


def test_lowercase_llm_output_is_accepted_without_retry(fake_llm):
    import json
    fake_llm([json.dumps({"priority": "p3", "category": "network ", "suggested_team": "Network",
                          "confidence": 0.9, "reasoning": "Motiv de test.", "citations": []})])
    t = service.submit_ticket("Switch-ul de pe etajul 2 pierde pachete intermitent")["ticket"]
    assert t["attempts"] == 1 and t["status"] == "auto_routed"


def test_off_topic_ticket_skips_llm_entirely(fake_llm):
    fake_llm([])    # orice apel LLM ar esua
    r = service.submit_ticket("Ma doare capul si as vrea o pizza cu ciuperci")
    t = r["ticket"]
    assert (t["status"], t["decision_rule"]) == ("pending_approval", "out_of_scope")
    assert service.ticket_detail(t["id"])["usage"] == []        # 0 tokeni


def test_force_new_bypasses_duplicate_detection(fake_llm):
    fake_llm([label("P3", "Software", "Application Support", 0.9)])
    first = service.submit_ticket("Aplicatia de contabilitate se blocheaza la export")["ticket"]
    fake_llm([label("P3", "Software", "Application Support", 0.9)])
    again = service.submit_ticket("Aplicatia de contabilitate se blocheaza la export", force_new=True)["ticket"]
    assert again["status"] != "duplicate" and again["id"] != first["id"]


def test_rejected_ticket_is_not_reused_as_duplicate(fake_llm):
    fake_llm([label("P3", "Network", "Network", 0.4)])
    a = service.submit_ticket("Internetul pierde conexiunea la fiecare cateva minute")["ticket"]
    service.review_ticket(a["id"], False, "mario", "prea vag")
    fake_llm([label("P3", "Network", "Network", 0.9)])
    b = service.submit_ticket("Internetul pierde conexiunea la fiecare cateva minute")["ticket"]
    assert b["status"] != "duplicate"


# ---------------- retrieval ----------------

def test_retrieval_returns_at_most_k_and_no_duplicate_subject_team_pairs():
    retrieval.ensure_index()
    docs = retrieval.history_retriever.invoke("Cannot access email, login failed")
    assert 1 <= len(docs) <= retrieval.history_retriever.k
    pairs = [(d.metadata["subject"], d.metadata["team"]) for d in docs]
    assert len(pairs) == len(set(pairs))
    dists = [d.metadata["distance"] for d in docs]
    assert dists == sorted(dists)                                # cele mai apropiate primele