# Rezultate evaluare — 2026-10-14T14:06

Set de test: 100 tichete (nevăzute la indexare/antrenare).

| Model | Prioritate acc. | Prioritate macro-F1 | Categorie acc. | Echipă acc. | JSON invalid % | Intervenție umană % | P1 ratate fără om | Latență p50 (ms) | Tokeni/tichet | Cost/1000 ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| few-shot RAG · groq:openai/gpt-oss-20b | 0.59 | 0.58 | 0.97 | 0.97 | 0.0 | 19.0 | 5 | 7541 | 996 | 0.1039 |
| few-shot RAG · ollama:llama3.2 | 0.53 | 0.521 | 0.99 | 0.99 | 0.0 | 37.0 | 4 | 2601 | 955 | 0.0 |
| LoRA · ollama:triaj-lora | 0.87 | 0.857 | 0.99 | 0.99 | 0.0 | — | — | 1112 | 221 | 0.0 |

## Manual vs agentic (simulare, model: few-shot RAG · groq:openai/gpt-oss-20b)

| Scenariu | Timp până la rutare (h) | Rutări greșite % | MTTR (h) | Decizii umane % | Auto-rezolvare % |
|---|---|---|---|---|---|
| Manual (baseline) | 1.03 | 20.0 | 38.14 | 100.0 | 0.0 |
| Agentic | 0.038 | 2.2 | 36.77 | 19.0 | 81.0 |

| Prioritate | MTTR manual (h) | MTTR agentic (h) |
|---|---|---|
| P1 | 3.74 | 3.46 |
| P2 | 13.48 | 12.88 |
| P3 | 37.74 | 36.47 |
| P4 | 80.68 | 77.88 |
