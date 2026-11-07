"""Guardrail (decizie). Cod determinist, fara LLM. Reguli evaluate in ordine; prima care
se aplica decide. Singurele doua motive care trimit un tichet clasificat la om: P1 si
confidence sub prag. Orice altceva (inconsistente de taxonomie, precedente slabe) nu
blocheaza rutarea automata -- doar riscul si increderea conteaza."""

import re
from typing import Optional

from agent.config import CONFIDENCE_THRESHOLD, OUT_OF_SCOPE_DISTANCE
from agent.schemas import Decision, TicketClassification

# Cuvinte care indica pericol fizic. Folosite in graph.py ca sa fortam prioritatea la P1
# -- nu e o regula separata aici. Pericolul fizic devine P1, deci trece prin regula
# p1_always_human de mai jos, nu printr-o cale separata.
# Potriviri pe CUVANT INTREG (\b), nu subsir: altfel "firewall" (fire), "focus" (foc),
# "years"/"parser" (ars) ar forta P1 pe tichete banale. Formele romanesti uzuale sunt acoperite.
SAFETY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\bsc[aâ]ntei\w*", r"\bsc[aâ]nteie\w*", r"\bsparks?\b", r"\bsparking\b",
    r"\bfum(ul|ează|eaza|egă|ega)?\b", r"\bsmok(e|ing)\b",
    r"\bfoc(ul)?\b", r"\bon fire\b", r"\bcaught fire\b", r"\bfire alarm\b",
    r"\bflac[aă]r[aă]\w*", r"\bflames?\b",
    r"\bmiros de ars\b", r"\bburning smell\b", r"\bsmell of burning\b", r"\bburnt\b",
    r"\belectrocut\w*", r"\belectric shock\b", r"\b[sș]oc electric\b",
    r"\bsupra[iî]nc[aă]lz\w*",
)]


def is_safety_hazard(text: str) -> bool:
    """True daca textul contine un semnal de pericol fizic. Cautare pe text brut, fara LLM."""
    return any(p.search(text or "") for p in SAFETY_PATTERNS)


RULES = [
    ("llm_unavailable", "LLM-ul nu a raspuns (cheie, limita, retea) -> triaj manual"),
    ("invalid_output", "LLM-ul nu a produs o clasificare valida -> triaj manual"),
    ("out_of_scope", f"niciun precedent IT apropiat (distanta > {OUT_OF_SCOPE_DISTANCE}) -> om, fara apel LLM"),
    ("p1_always_human", "P1 (inclusiv pericol fizic, fortat la P1) -> aprobare umana obligatorie"),
    ("low_confidence", f"confidence < {CONFIDENCE_THRESHOLD} -> aprobare umana"),
    ("auto", "orice altceva -> rutare automata"),
]


def decide(c: Optional[TicketClassification], llm_unavailable: bool = False, out_of_scope: bool = False,
           weak_match: bool = False, **_ignored) -> Decision:
    # weak_match si orice alt kwarg (similar_docs etc.) nu mai influenteaza decizia --
    # acceptate aici doar ca graph.py sa poata continua sa le trimita fara sa se schimbe.
    if out_of_scope:
        return Decision(status="pending_approval", rule="out_of_scope",
                        reason="Nu seamănă cu niciun incident IT cunoscut — verificare umană, fără clasificare automată.")
    if c is None and llm_unavailable:
        return Decision(status="pending_approval", rule="llm_unavailable",
                        reason="Modelul nu a răspuns (cheie, limită de rată sau rețea) — triaj manual.")
    if c is None:
        return Decision(status="pending_approval", rule="invalid_output",
                        reason="Agentul nu a produs o clasificare validă — triaj manual.")
    if c.priority == "P1":
        return Decision(status="pending_approval", rule="p1_always_human",
                        reason="Prioritate P1 — aprobare umană obligatorie (impact major).")
    if c.confidence < CONFIDENCE_THRESHOLD:
        return Decision(status="pending_approval", rule="low_confidence",
                        reason=f"Confidence {c.confidence:.2f} sub pragul de {CONFIDENCE_THRESHOLD:.2f} — aprobare umană.")
    return Decision(status="auto_routed", rule="auto", reason="Risc scăzut — rutare automată.")