# ITSM Ticket Triage Agent

An agent that reads a free text IT ticket, in Romanian or English, and decides priority (P1 to P4), category, and responsible team based on similar past tickets. It then decides on its own whether to auto route the ticket or send it to a human for approval. Every decision comes with reasoning, cited sources, and a full trace in Arize Phoenix.

The LLM only proposes. Its output is a JSON validated with Pydantic, and the final decision is made by a deterministic guardrail, not the model.

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

Add your GROQ_API_KEY to `.env` (free at console.groq.com).

| Service | Address |
|---|---|
| Classification, KPI & cost, Jira & integrations (Streamlit) | http://localhost:8501 |
| Approvals, separate app for reviewers | http://localhost:8502 |
| API, interactive docs | http://localhost:8000/docs |
| Arize Phoenix | http://localhost:6006 |

The first build takes a few minutes because the image bundles the embedding model (~240 MB), so later startups don't need to download anything. The data (400 historical tickets) is already in the repo, and the index builds itself on first run.

## How it works, in short

1. **Classification**: type your name in the sidebar, then a ticket, for example "AWS servers are down, the payment app isn't working for any customer." You get the priority, team, reasoning, citations, and similar past examples.
2. Submit a low risk ticket, for example "Outlook stopped syncing, not urgent": it gets auto routed. Submit the same text again and it's recognized as a duplicate, no LLM call needed.
3. **Approvals** (http://localhost:8502, a separate app, reviewers only see this): P1 tickets land here. You can approve them, optionally with a team correction.
4. **Phoenix**, project `triaj-agent`, Sessions tab, `INC-000X`: the ticket's full path, from the retriever and the documents it pulled in, to the LLM call with token usage, the guardrail (proposal versus decision), the tool that ran, and the human's approval.
5. **KPI & FinOps**: auto resolution rate, human intervention, time to routing, tokens and cost per ticket.

## Jira, both directions

```
New issue in Jira  (webhook or periodic sync)  agent  safety rules
      ^                                                    |
      |______ comment with the decision, priority, labels__|
```

Inbound: `POST /webhooks/jira` on the Issue created event, or JQL polling every `JIRA_POLL_SECONDS` seconds. Polling is the simple option on a laptop, since Jira Cloud can't reach `localhost` without a tunnel like ngrok.

Each Jira key is classified only once, no matter how many webhooks or syncs come in (idempotent).

Outbound: a comment with the decision and reasoning, the Jira priority set accordingly (P1 becomes Highest, P4 becomes Low), and labels (`triaj-ai`, `triaj-auto` or `triaj-review`, `team-...`). After a human approves or rejects, another comment follows with any corrections. Every action is logged and can be retried manually.

Security: `JIRA_WEBHOOK_SECRET`, verified through the HMAC signature Jira Cloud sends.

Without credentials in `.env`, the system runs in simulation mode: the flow is identical, but what would have been written to Jira only shows up in the local log.

## What the project covers

| Requirement | Where it lives |
|---|---|
| Documented architecture (roles, tools, handoffs, state) | `docs/architecture.md` |
| Separation of reasoning and execution, Pydantic validated JSON | `agent/classifier.py`, `agent/schemas.py`, `agent/router.py`, `agent/tools.py` |
| Open source model, zero cost | Groq `openai/gpt-oss-20b` (free tier), plus local Ollama for few-shot and LoRA |
| RAG with ChromaDB, citations, RAGAS evaluation | `agent/retrieval.py`, `scripts/ragas_eval.py` |
| Human-in-the-loop with justified thresholds | `agent/router.py`, the Approvals page, `docs/architecture.md` |
| Audit trail and observability with Arize Phoenix | `agent/telemetry.py`, the `audit_log` table |
| Realistic mock data, 500 tickets | 400 historical plus 100 test, `scripts/import_kaggle.py` |
| Measured KPIs, manual versus agentic | KPI page, `scripts/evaluate.py`, `docs/evaluation.md` |
| FastAPI in Docker plus Streamlit, full end to end flow | `api/`, `ui/`, `docker-compose.yml` |
| Few-shot versus fine-tuned LoRA | `finetune/lora_finetune.ipynb`, `scripts/evaluate.py` |

## Evaluation

```bash
docker compose exec api python scripts/evaluate.py
docker compose exec api python scripts/ragas_eval.py --n 20
```

Results land in `eval/results/` and on the KPI page. On 100 test tickets:

| Model | Priority macro-F1 | Latency p50 | Tokens/ticket | Cost/1000 |
|---|---|---|---|---|
| few-shot gpt-oss-20b | 0.58 | 7541 ms | 996 | $0.1039 |
| few-shot llama3.2 3B | 0.521 | 2601 ms | 955 | $0 |
| LoRA llama3.2 3B (400 tickets) | 0.857 | 1112 ms | 221 | $0 |

The manual versus agentic simulation shows time to routing dropping from 1.03 h to 0.038 h, misrouted tickets from 20% to 2.2%, and human decisions from 100% to 19%. Details and limitations in `docs/evaluation.md`.

## Running without Docker

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-eval.txt
export GROQ_API_KEY=...
docker run -d -p 6006:6006 arizephoenix/phoenix:version-20.16.0
uvicorn api.main:app --port 8000
streamlit run ui/app.py
pytest
```

## Structure

```
agent/      the agent's core (LangGraph graph, classification, router, tools, Jira, RAG, DB)
api/        FastAPI
ui/         Streamlit, classification and approvals as separate apps
scripts/    Kaggle import, evaluation, RAGAS
finetune/   notebook, modelfile, LoRA training data
data/       tickets.csv and test_tickets.csv
docs/       architecture, evaluation, FinOps
tests/      unit tests, full flow, API
```

## Configuration

Everything lives in `.env` and `agent/config.py`:

| Variable | Default |
|---|---|
| `GROQ_API_KEY` | required for Groq |
| `LLM_PROVIDER` | `groq` (or `ollama`) |
| `GROQ_MODEL` | `openai/gpt-oss-20b` |
| `OLLAMA_MODEL` | `llama3.2` |
| `TRACING_ENABLED` | `true` |
| `APPROVER_CODE` | empty, optional |
| `CONFIDENCE_THRESHOLD` in config.py | `0.70` |
