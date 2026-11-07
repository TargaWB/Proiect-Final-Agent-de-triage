"""Observabilitate cu Arize Phoenix prin OpenTelemetry/OpenInference.

- LangChain/LangGraph sunt instrumentate automat: fiecare nod, retriever, apel LLM (cu
  prompt, raspuns, tokeni) si tool devine un span.
- Adaugam manual spanuri pentru ce nu e LangChain: guardrail-ul si aprobarea umana
  (cine a aprobat, ce a corectat).
- Toate spanurile unui tichet au session.id = codul tichetului -> in Phoenix, la Sessions,
  vezi tot istoricul unui tichet: clasificare, decizie, aprobare, executie.
Daca Phoenix nu ruleaza, aplicatia merge normal; doar nu se trimit trace-uri."""

import json
import logging
from contextlib import contextmanager

from opentelemetry import trace

from agent.config import PHOENIX_ENDPOINT, PHOENIX_PROJECT, TRACING_ENABLED

log = logging.getLogger(__name__)
_initialized = False
_provider = None   # provider propriu, NU global: altfel FastAPI trimite si spanuri HTTP (ex. /health la 10s)


def init_tracing():
    global _initialized, _provider
    if _initialized or not TRACING_ENABLED:
        return
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from phoenix.otel import register

        _provider = register(project_name=PHOENIX_PROJECT, endpoint=PHOENIX_ENDPOINT,
                             batch=True, verbose=False, set_global_tracer_provider=False)
        LangChainInstrumentor().instrument(tracer_provider=_provider)
        _initialized = True
        log.info("Tracing activ -> %s (proiect %s)", PHOENIX_ENDPOINT, PHOENIX_PROJECT)
    except Exception as e:  # tracing-ul nu are voie sa opreasca aplicatia
        log.warning("Tracing dezactivat: %s", e)


def tracer():
    return (_provider or trace.get_tracer_provider()).get_tracer("triaj-agent")


@contextmanager
def span(name: str, kind: str = "CHAIN", **attributes):
    """Span manual cu tip OpenInference (CHAIN, GUARDRAIL, TOOL, EVALUATOR...)."""
    from openinference.instrumentation import get_attributes_from_context
    from openinference.instrumentation.langchain import get_current_span

    # parinte = nodul LangGraph care ruleaza acum (ex. guardrail sub "decide"), daca exista
    lc_span = get_current_span()
    parent = trace.set_span_in_context(lc_span) if lc_span and lc_span.get_span_context().is_valid else None
    with tracer().start_as_current_span(name, context=parent) as s:
        s.set_attribute("openinference.span.kind", kind)
        for k, v in get_attributes_from_context():   # session.id, user.id din using_session/using_user
            s.set_attribute(k, v)
        for k, v in attributes.items():
            if v is None:
                continue
            s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v, default=str))
        yield s


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
