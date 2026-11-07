"""Contractele dintre straturi. LLM-ul poate doar sa PROPUNA un TicketClassification;
orice raspuns care nu trece validarea de aici e respins inainte sa ajunga la decizie."""

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from agent.config import CATEGORIES

Priority = Literal["P1", "P2", "P3", "P4"]
Category = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
Status = Literal["received", "auto_routed", "pending_approval", "approved", "rejected", "duplicate"]


def _clean_priority(v):
    """LLM-ul uneori raspunde 'p1', ' P1 ' sau 'P1.' in loc de 'P1'. Normalizam
    inainte de validarea stricta Literal, ca sa nu pierdem un raspuns bun doar
    din cauza formatarii -- fara sa slabim validarea in sine."""
    if isinstance(v, str):
        return v.strip().upper().rstrip(".")
    return v


def _clean_category(v):
    """LLM-ul uneori raspunde 'hardware' sau 'Hardware ' in loc de 'Hardware'.
    Normalizam case/spatii; categoria tot trebuie sa fie una din cele permise,
    altfel Literal respinge raspunsul exact ca inainte."""
    if isinstance(v, str):
        v = v.strip()
        for c in CATEGORIES:
            if v.lower() == c.lower():
                return c
    return v


PriorityNorm = Annotated[Priority, BeforeValidator(_clean_priority)]
CategoryNorm = Annotated[Category, BeforeValidator(_clean_category)]


class TicketClassification(BaseModel):
    """Propunerea LLM-ului (reasoning). Nu executa nimic."""
    priority: PriorityNorm
    category: CategoryNorm
    suggested_team: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=3, max_length=600)
    citations: List[str] = Field(default_factory=list)

    @field_validator("suggested_team", "reasoning")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LabelOnly(BaseModel):
    """Iesirea modelului LoRA (antrenat doar pe etichete) -- folosita la evaluare."""
    priority: PriorityNorm
    category: CategoryNorm
    suggested_team: str


class Decision(BaseModel):
    """Rezultatul guardrail-ului (determinist)."""
    status: Literal["auto_routed", "pending_approval"]
    rule: str
    reason: str


class LLMUsage(BaseModel):
    provider: str
    model: str
    purpose: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


# ---------- API ----------

class TicketIn(BaseModel):
    text: str = Field(min_length=5, max_length=4000)
    submitted_by: Optional[str] = None
    force_new: bool = False


class ReviewIn(BaseModel):
    approved: bool
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = ""
    priority: Optional[Priority] = None   # corectie optionala facuta de om
    team: Optional[str] = None