"""Teste fara retea si fara cheie: LLM-ul e inlocuit cu un model fals care intoarce JSON
predefinit (cu usage_metadata, ca sa testam si FinOps), iar trace-urile merg intr-un
exporter in memorie, ca sa verificam exact ce ar primi Phoenix."""

import json
import os
import tempfile

_STATE = tempfile.mkdtemp(prefix="triaj-test-")
os.environ["STATE_DIR"] = _STATE
os.environ["EVAL_DIR"] = os.path.join(_STATE, "eval")
os.environ["TRACING_ENABLED"] = "false"
os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from openinference.instrumentation.langchain import LangChainInstrumentor  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(_provider)
LangChainInstrumentor().instrument(tracer_provider=_provider)


def label(priority="P3", category="Network", team="Network", confidence=0.85):
    return json.dumps({"priority": priority, "category": category, "suggested_team": team,
                       "confidence": confidence, "reasoning": "Motiv de test.", "citations": []})


@pytest.fixture
def fake_llm(monkeypatch):
    """fake_llm([raspuns1, raspuns2...]) -> urmatoarele apeluri LLM intorc aceste texte."""
    import agent.classifier as classifier

    def set_outputs(outputs):
        msgs = [AIMessage(content=o, usage_metadata={"input_tokens": 900, "output_tokens": 80,
                                                     "total_tokens": 980}) for o in outputs]
        monkeypatch.setattr(classifier, "get_chat_model",
                            lambda provider=None, model=None, temperature=0.1: GenericFakeChatModel(messages=iter(msgs)))
    return set_outputs


@pytest.fixture
def spans():
    EXPORTER.clear()
    return EXPORTER
