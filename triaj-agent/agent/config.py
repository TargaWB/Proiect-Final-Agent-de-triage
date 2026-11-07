"""Configurare centrala. Tot ce e prag, model, cale sau presupunere de simulare sta aici."""

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
STATE_DIR = os.environ.get("STATE_DIR", os.path.join(ROOT, "state"))   # volum Docker
EVAL_DIR = os.environ.get("EVAL_DIR", os.path.join(ROOT, "eval", "results"))

TICKETS_CSV = os.path.join(DATA_DIR, "tickets.csv")        # istoric indexat (RAG + few-shot + LoRA train)
TEST_CSV = os.path.join(DATA_DIR, "test_tickets.csv")      # set de test, niciodata indexat
DB_PATH = os.path.join(STATE_DIR, "triaj.db")
CHROMA_PATH = os.path.join(STATE_DIR, "chroma")

# ---------------- LLM ----------------
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")                 # groq | ollama
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_RETRIES = 1          # reincercari daca JSON-ul nu trece validarea Pydantic
FEW_SHOT_K = 3           # cate tichete similare intra in prompt ca exemple

# FinOps: pret de lista per 1M tokeni (USD). Pe free tier platim 0, dar calculam
# "costul echivalent" ca sa stim cat ar costa in productie.
PRICING = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}
LOCAL_PRICE = (0.0, 0.0)  # modele Ollama, rulate local

# ---------------- Embedding ----------------
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"   # RO + EN, local

# ---------------- Guardrails ----------------
CONFIDENCE_THRESHOLD = 0.70
# Tichete trimise anterior:
# - duplicat = acelasi text dupa normalizare (litere mici, fara punctuatie/spatii in plus) ->
#   clasificarea se refoloseste fara LLM. NU folosim distanta de embedding pentru asta:
#   "imprimanta etaj 2" vs "imprimanta etaj 3" au distanta 0.04, dar sunt incidente diferite.
# - similar = distanta cosinus <= prag -> aratat ca exemplu si dat LLM-ului ca precedent.
#   Calibrare: parafraza ~0.08-0.15, problema inrudita ~0.2-0.35, alt subiect ~0.75.
SIMILAR_DISTANCE = 0.35
# Filtru de relevanta: daca cel mai apropiat precedent e mai departe de prag, tichetul nu pare
# sa fie un incident IT din domeniul cunoscut -> nu se apeleaza LLM, merge la om.
# Calibrare (distanta top-1 la istoric, indexul e in engleza):
#   100 tichete de test IT (engleza): max 0.454; tichete IT scurte in romana: 0.12-0.60;
#   15 texte fara legatura cu IT (romana): 0.55-0.92 (10 din 15 peste 0.65).
# Cele doua grupuri se suprapun intre 0.50 si 0.65, deci doua praguri:
#   > 0.65  -> out_of_scope: nu se apeleaza LLM, merge la om
#   0.50-0.65 -> weak_match: LLM propune, dar tichetul merge mereu la om
WEAK_MATCH_DISTANCE = 0.50
OUT_OF_SCOPE_DISTANCE = 0.65

# ---------------- Taxonomie ----------------
CATEGORY_TO_TEAM = {
    "Hardware": "Desktop Support",
    "Software": "Application Support",
    "Network": "Network",
    "Access/Permissions": "Identity & Access",
    "Email/Communication": "Messaging",
    "Database": "DBA",
    "Security": "SecOps",
    "Cloud/Infrastructure": "Infrastructure",
}
CATEGORIES = list(CATEGORY_TO_TEAM)
TEAMS = sorted(set(CATEGORY_TO_TEAM.values()))
PRIORITIES = ["P1", "P2", "P3", "P4"]

# ---------------- Observabilitate ----------------
TRACING_ENABLED = os.environ.get("TRACING_ENABLED", "true").lower() == "true"
PHOENIX_ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
PHOENIX_PROJECT = os.environ.get("PHOENIX_PROJECT_NAME", "triaj-agent")

# ---------------- Simulare KPI (presupuneri, documentate in docs/evaluation.md) ----------------
# Timpul de rezolutie per prioritate vine din date reale (time_to_resolution_hours, proces manual).
# Presupunerile de mai jos modeleaza doar partea de triaj si re-rutare.
SIM = {
    # asteptare in coada + citire + decizie de catre dispecer, in ore, per prioritate
    "manual_triage_hours": {"P1": 0.25, "P2": 0.5, "P3": 1.0, "P4": 2.0},
    # rata de rutare gresita la triajul manual (presupunere; se poate ajusta)
    "manual_misroute_rate": 0.20,
    # timp pierdut cand un tichet ajunge la echipa gresita si e re-rutat, in ore
    "reroute_penalty_hours": {"P1": 0.5, "P2": 1.0, "P3": 2.0, "P4": 4.0},
    # cat dureaza aprobarea umana cand contextul e deja pregatit de agent, in ore
    "review_hours": {"P1": 0.1, "P2": 0.25, "P3": 0.5, "P4": 0.5},
    # probabilitatea ca omul sa prinda o clasificare gresita la aprobare
    "review_catch_rate": 0.8,
}
