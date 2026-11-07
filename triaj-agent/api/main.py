"""API FastAPI. Interfata Streamlit (si orice alt client) vorbeste doar prin aceste endpoint-uri."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from agent import config, db, jira, retrieval, service
from agent.llm import default_spec
from agent.schemas import ReviewIn, TicketIn
from agent.telemetry import init_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tracing()
    retrieval.ensure_index()
    if jira.start_polling(service.submit_ticket):
        log.info("Jira: polling activ (JIRA_POLL_SECONDS=%s)", jira.settings()["poll_seconds"])
    yield
    jira.stop_polling()


app = FastAPI(title="Agent de Triaj ITSM", version="1.1", lifespan=lifespan)


# ════════════════════════════════════════════════════════════════
# Endpoints existente
# ════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def get_config():
    provider, model = default_spec()
    return {"provider": provider, "model": model, "confidence_threshold": config.CONFIDENCE_THRESHOLD,
            "similar_distance": config.SIMILAR_DISTANCE, "categories": config.CATEGORY_TO_TEAM,
            "teams": config.TEAMS, "priorities": config.PRIORITIES,
            "phoenix_project": config.PHOENIX_PROJECT, "tracing": config.TRACING_ENABLED}


@app.post("/tickets", status_code=201)
def create_ticket(body: TicketIn):
    try:
        return service.submit_ticket(body.text, body.submitted_by, body.force_new)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.get("/tickets")
def list_tickets(status: str | None = None, limit: int = Query(50, le=500)):
    return db.list_tickets(status, limit)


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int):
    t = service.ticket_detail(ticket_id)
    if t is None:
        raise HTTPException(404, "Tichet inexistent.")
    return t


@app.get("/approvals")
def approvals():
    return db.pending_queue()


@app.post("/tickets/{ticket_id}/review")
def review(ticket_id: int, body: ReviewIn, background: BackgroundTasks):
    if db.get_ticket(ticket_id) is None:
        raise HTTPException(404, "Tichet inexistent.")
    try:
        t = service.review_ticket(ticket_id, body.approved, body.reviewer.strip(), body.note,
                                  body.priority, body.team)
    except service.ReviewError as e:
        raise HTTPException(409, str(e))
    if jira.link_for_ticket(ticket_id):  # decizia omului ajunge si in issue-ul Jira
        background.add_task(jira.push, ticket_id, "reviewed")
    return t


@app.get("/kpis")
def kpis():
    return {"live": service.kpis(), "finops": service.finops(), "evaluation": service.evaluation_results()}


@app.post("/index/rebuild")
def rebuild_index():
    return retrieval.build_index()


# ════════════════════════════════════════════════════════════════
# Jira: webhook (intrare), polling, scriere inapoi (iesire)
# ════════════════════════════════════════════════════════════════

IGNORED_JIRA_EVENTS = {"jira:issue_deleted", "comment_created", "comment_updated"}


@app.post("/webhooks/jira", status_code=201)
async def jira_webhook(request: Request, background: BackgroundTasks, token: str | None = None):
    """Jira Cloud/Server trimite aici evenimentul `jira:issue_created`. Agentul clasifica issue-ul,
    apoi scrie inapoi in Jira (comentariu + prioritate + etichete) in fundal.
    Idempotent: aceeasi cheie Jira nu se clasifica de doua ori."""
    raw = await request.body()
    if not jira.verify_signature(raw, request.headers.get("X-Hub-Signature"), token):
        raise HTTPException(401, "Semnatura webhook-ului Jira nu e valida (JIRA_WEBHOOK_SECRET).")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Payload JSON invalid.")
    event = payload.get("webhookEvent", "jira:issue_created")
    issue = payload.get("issue") or {}
    if event in IGNORED_JIRA_EVENTS:
        return {"source": "jira", "ignored": event}

    log.info("Webhook Jira %s: %s", event, issue.get("key"))
    try:
        r = await run_in_threadpool(jira.ingest, issue, "webhook", service.submit_ticket)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    if r["created"]:
        background.add_task(jira.push, r["ticket_id"], "classified")
    ticket = db.get_ticket(r["ticket_id"])
    return {"source": "jira", "jira_key": r["jira_key"], "created": r["created"], "ticket": ticket,
            "duplicate_of": (r["result"] or {}).get("duplicate_of"),
            "writeback": "programat" if r["created"] else "deja facut"}


@app.get("/integrations/jira/status")
def jira_status():
    return jira.status()


@app.post("/integrations/jira/test")
def jira_test():
    return jira.test_connection()


@app.post("/integrations/jira/sync")
def jira_sync():
    """Cauta acum issue-uri noi in Jira (JQL) si le trece prin agent."""
    return jira.sync_once(service.submit_ticket)


@app.get("/integrations/jira/events")
def jira_events(limit: int = Query(40, le=200)):
    return jira.events(limit)


@app.get("/integrations/jira/tickets")
def jira_tickets(limit: int = Query(40, le=200)):
    return jira.linked_tickets(limit)


@app.post("/integrations/jira/push/{ticket_id}")
def jira_push(ticket_id: int):
    """Retrimite manual rezultatul in Jira (dupa o eroare de retea, de ex.)."""
    t = db.get_ticket(ticket_id)
    if t is None:
        raise HTTPException(404, "Tichet inexistent.")
    event = "reviewed" if t["status"] in ("approved", "rejected") else "classified"
    return jira.push(ticket_id, event)


# ════════════════════════════════════════════════════════════════
# Informatii baza de date  (GET /db/info)
# ════════════════════════════════════════════════════════════════

@app.get("/db/info")
def db_info():
    """Informatii despre starea bazei de date si a indexului RAG."""
    import os
    tickets_total = db.query("SELECT COUNT(*) n FROM tickets")[0]["n"]
    by_status = db.query("SELECT status, COUNT(*) n FROM tickets GROUP BY status")
    index_docs = 0
    try:
        index_docs = retrieval._collection(retrieval.HISTORY).count()
        index_docs += retrieval._collection(retrieval.SUBMITTED).count()
    except Exception:
        pass
    db_size = 0
    try:
        db_size = os.path.getsize(config.DB_PATH)
    except OSError:
        pass
    return {
        "db_path": config.DB_PATH,
        "db_size_mb": round(db_size / (1024 * 1024), 2),
        "tickets_total": tickets_total,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "index_docs": index_docs,
        "chroma_path": config.CHROMA_PATH,
    }


# ════════════════════════════════════════════════════════════════
# Retentie tichete  (POST /maintenance/retention)
# ════════════════════════════════════════════════════════════════

class RetentionConfig(BaseModel):
    archive_after_days: int = 90          # dupa cate zile se arhiveaza tichetele (text trunchiat, audit sters)
    delete_audit_after_days: int = 90     # log-urile de audit detaliate se sterg dupa atatea zile
    delete_usage_after_days: int = 90     # consumul LLM detaliat se sterge dupa atatea zile
    purge_after_days: int = 365           # dupa cate zile se sterge textul complet (ramane doar eticheta)
    dry_run: bool = True                  # doar raporteaza ce ar face, fara sa schimbe nimic


@app.post("/maintenance/retention")
def run_retention(cfg: RetentionConfig = RetentionConfig()):
    """Politica de retentie in 3 trepte:

    1. Tichete > archive_after_days (implicit 90):
       - Se sterg log-urile de audit detaliate (tabel audit_log)
       - Se sterge consumul LLM detaliat (tabel llm_usage)
       - Tichetul ramane cu textul complet si clasificarea

    2. Tichete > purge_after_days (implicit 365):
       - Textul tichetului se inlocuieste cu un rezumat scurt:
         "[ARHIVAT] Categorie: X, Prioritate: Y, Echipa: Z"
       - Se pastreaza etichetele (priority, category, team) — utile pentru reantrenare LoRA
       - Se sterge din indexul ChromaDB (submitted)

    3. Indexul ChromaDB (submitted) se curata de tichetele arhivate.

    dry_run=true (implicit) doar raporteaza fara sa faca modificari.
    """
    now = datetime.now()
    archive_cutoff = (now - __import__("datetime").timedelta(days=cfg.archive_after_days)).isoformat(timespec="seconds")
    purge_cutoff = (now - __import__("datetime").timedelta(days=cfg.purge_after_days)).isoformat(timespec="seconds")

    # Ce ar fi afectat
    to_clean_audit = db.query(
        "SELECT id, created_at FROM tickets WHERE created_at < ? AND status NOT IN ('received', 'pending_approval')",
        (archive_cutoff,))
    to_purge_text = db.query(
        "SELECT id, created_at, priority, category, team FROM tickets WHERE created_at < ? AND text NOT LIKE '[ARHIVAT]%%'",
        (purge_cutoff,))

    report = {
        "dry_run": cfg.dry_run,
        "archive_cutoff": archive_cutoff,
        "purge_cutoff": purge_cutoff,
        "audit_logs_to_delete": len(to_clean_audit),
        "usage_logs_to_delete": len(to_clean_audit),
        "tickets_to_purge_text": len(to_purge_text),
    }

    if cfg.dry_run:
        return {**report, "action": "dry_run — nu s-a modificat nimic"}

    # 1. Sterge audit + usage vechi
    if to_clean_audit:
        ids = [t["id"] for t in to_clean_audit]
        placeholders = ",".join("?" * len(ids))
        with db.conn() as c:
            c.execute(f"DELETE FROM audit_log WHERE ticket_id IN ({placeholders})", ids)
            c.execute(f"DELETE FROM llm_usage WHERE ticket_id IN ({placeholders})", ids)
        report["audit_deleted"] = True

    # 2. Anonimizeaza textul tichetelor foarte vechi
    if to_purge_text:
        for t in to_purge_text:
            summary = f"[ARHIVAT] Categorie: {t['category'] or '—'}, Prioritate: {t['priority'] or '—'}, Echipa: {t['team'] or '—'}"
            db.update_ticket(t["id"], text=summary)
            # Sterge din indexul de tichete trimise (submitted)
            try:
                retrieval._collection(retrieval.SUBMITTED).delete(ids=[str(t["id"])])
            except Exception:
                pass
        report["text_purged"] = True

    report["action"] = "executat"
    log.info("Retentie: audit=%d, purge=%d", len(to_clean_audit), len(to_purge_text))
    return report
