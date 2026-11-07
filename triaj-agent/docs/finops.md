# Usage, consum și FinOps

## Framework compatibil OpenTelemetry/OpenInference

Agentul e construit pe **LangChain + LangGraph**, nu pe Python pur. Asta aduce
instrumentare automată prin `openinference-instrumentation-langchain`: fiecare apel LLM
exportă spre Phoenix, fără cod extra:

- `llm.token_count.prompt`, `llm.token_count.completion`, `llm.token_count.total`
- modelul, parametrii, promptul și răspunsul complet
- latența fiecărui pas (retrieval, LLM, guardrail, tool)

În Phoenix: **Projects → triaj-agent → Metrics** (tokeni și latență în timp), sau pe
fiecare trace.

## Ce contabilizează aplicația

Fiecare apel LLM se salvează în tabela `llm_usage`: tichetul, modelul, scopul (`classify` /
`classify_retry`), tokenii, latența și costul echivalent.

```
cost_echivalent = tokeni_input × preț_input + tokeni_output × preț_output   (per 1M tokeni)
```

| Model | Input $/1M | Output $/1M | Unde |
|---|---|---|---|
| `openai/gpt-oss-20b` (Groq) | 0.075 | 0.30 | producție |
| `openai/gpt-oss-120b` (Groq) | 0.15 | 0.60 | judecător RAGAS |
| modele Ollama | 0 | 0 | local (evaluare, LoRA) |

Prețurile sunt în `agent/config.py → PRICING`. Pe free tier, costul real plătit e $0.
Costul echivalent arată cât ar costa aceeași încărcare în producție.

## Pârghii de cost implementate

| Pârghie | Efect |
|---|---|
| **Cache de duplicate** | Tichet identic cu unul trimis → clasificare refolosită, 0 tokeni. Tokenii economisiți apar în dashboard. |
| **Retrieval local** | Embedding-ul rulează local (ONNX), fără API: 0 cost pe fiecare căutare. |
| **3 exemple, nu tot istoricul** | Promptul rămâne mic (~1k tokeni), indiferent câte tichete are istoricul. |
| **`reasoning_effort="low"`** | gpt-oss raționează mai scurt: mai puțini tokeni de output, latență mai mică. |
| **O singură reîncercare** | La JSON invalid, max. o reîncercare; reîncercările sunt numărate separat. |
| **Model mic + LoRA** | Dacă LoRA câștigă comparația, clasificarea poate rula local, cu cost 0. |

## Dashboard (pagina KPI & FinOps)

- apeluri LLM și reîncercări
- tokeni per tichet
- cost echivalent total și **proiectat la 1.000 de tichete**
- tichete servite din cache și tokeni economisiți
- defalcare pe model (apeluri, tokeni, latență medie, cost)

Datele brute: `GET /kpis` → `finops`.
