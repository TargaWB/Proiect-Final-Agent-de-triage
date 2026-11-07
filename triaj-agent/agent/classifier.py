"""Reasoning layer. LLM-ul primeste tichetul + exemple few-shot alese prin RAG si PROPUNE un
JSON. Raspunsul trece prin validare Pydantic; daca e invalid, i se cere o singura corectie.
Niciun raspuns nevalidat nu ajunge la decizie."""

import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from agent.config import CATEGORY_TO_TEAM, MAX_RETRIES
from agent.llm import default_spec, get_chat_model, usage_from
from agent.schemas import LLMUsage, TicketClassification

TAXONOMY = "\n".join(f"- {c} -> echipa \"{t}\"" for c, t in CATEGORY_TO_TEAM.items())

SYSTEM = f"""Esti agentul de triaj al unui service desk IT. Primesti un tichet nou (romana sau engleza)
si tichete istorice rezolvate, similare, cu eticheta lor corecta. Propui o clasificare.

Raspunde STRICT cu un obiect JSON, fara alt text:
{{"priority": "P1|P2|P3|P4", "category": "...", "suggested_team": "...", "confidence": 0.0-1.0,
  "reasoning": "1-2 propozitii in romana", "citations": ["id-urile exemplelor pe care te-ai bazat"]}}

Categorii permise si echipa fiecareia:
{TAXONOMY}

Prioritate:
- P1: serviciu critic oprit pentru multi utilizatori, productie blocata, incident de securitate activ, termen de minute.
- P2: impact serios dar limitat (o persoana/echipa blocata), trebuie rezolvat azi.
- P3: deranjant, exista ocolire, poate astepta cateva zile.
- P4: cerere de rutina sau problema minora, fara urgenta.
Urgenta exprimata de utilizator ("all work has stopped", "sla breach", "whenever you get a chance") conteaza.

Exemple la granita, ca sa calibrezi corect (nu doar definitia abstracta conteaza, ci scara impactului):
- "Serverul de productie care ruleaza aplicatia de facturare pentru toti clientii a picat" -> P1
  (sistem critic de business, TOTI clientii afectati, nu doar un departament)
- "Dashboard-ul de vanzari e lent si da timeout pentru toata echipa din teren" -> P2
  (un departament intreg blocat, dar nu e productia principala oprita)
- "Nu pot exporta un raport din ERP, am nevoie de el pana diseara" -> P3
  (un singur utilizator, exista ocolire -- export manual, trimis mai tarziu -- chiar daca
  utilizatorul foloseste cuvinte ca "urgent" sau "ACUM")
- "As vrea o a doua monitoare pentru biroul meu" -> P4
  (cerere de rutina, fara impact asupra muncii curente)
Ton alarmant sau majuscule NU inseamna automat prioritate mare -- uita-te la impactul descris
(cati oameni, ce sistem, exista alternativa), nu la cat de dramatic suna textul.

confidence = cat de sigur esti. Daca tichetul e vag, nu pare o problema IT sau nu seamana cu
niciun exemplu, da confidence sub 0.6. Citeaza doar id-uri din exemple."""


@dataclass
class ClassificationResult:
    classification: Optional[TicketClassification]
    usages: List[LLMUsage] = field(default_factory=list)
    attempts: int = 0
    error: Optional[str] = None
    llm_unavailable: bool = False
    provider: str = ""
    model: str = ""


def _examples_block(similar: List[Document], previous: List[dict]) -> str:
    parts = []
    for d in similar:
        m = d.metadata
        label = {"priority": m["priority"], "category": m["category"], "suggested_team": m["team"]}
        parts.append(f"[{m['id']}] {d.page_content}\n-> {json.dumps(label)}")
    for p in previous:
        if not p.get("priority"):
            continue
        confirmed = "confirmat" if p["status"] in ("approved", "auto_routed") else "neconfirmat inca"
        label = {"priority": p.get("final_priority") or p["priority"], "category": p["category"],
                 "suggested_team": p.get("final_team") or p["team"]}
        parts.append(f"[{p['code']}] (trimis anterior, {confirmed}) {p['text']}\n-> {json.dumps(label)}")
    return "\n\n".join(parts) if parts else "(nu exista exemple relevante)"


def build_messages(text: str, similar: List[Document], previous: List[dict]):
    return [
        SystemMessage(SYSTEM),
        HumanMessage(f"Exemple similare:\n\n{_examples_block(similar, previous)}\n\n"
                     f"Tichet nou:\n{text}\n\nRaspunde doar cu JSON-ul."),
    ]


def classify(text: str, similar: List[Document], previous: List[dict] | None = None,
             provider: str | None = None, model: str | None = None) -> ClassificationResult:
    provider, model = (provider or default_spec()[0]), (model or default_spec()[1])
    llm = get_chat_model(provider, model)
    messages = build_messages(text, similar, previous or [])
    result = ClassificationResult(None, provider=provider, model=model)

    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            msg = llm.invoke(messages, config={"run_name": "llm_classify", "tags": ["reasoning"]})
        except Exception as e:  # cheie invalida, rate limit, retea: tichetul nu se pierde, merge la om
            result.error = f"LLM indisponibil ({type(e).__name__}): {str(e)[:200]}"
            result.llm_unavailable = True
            result.attempts = attempt + 1
            return result
        result.usages.append(usage_from(msg, provider, model, "classify" if attempt == 0 else "classify_retry",
                                        (time.perf_counter() - t0) * 1000))
        result.attempts = attempt + 1
        try:
            result.classification = TicketClassification(**json.loads(msg.content))
            result.error = None
            return result
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            result.error = f"{type(e).__name__}: {str(e)[:300]}"
            messages = messages + [AIMessage(msg.content),
                                   HumanMessage(f"Raspunsul nu respecta schema ({result.error}). "
                                                "Trimite din nou DOAR JSON-ul corect.")]
    return result