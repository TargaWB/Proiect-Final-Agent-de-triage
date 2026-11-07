"""Evaluare pe setul de test (data/test_tickets.csv, niciodata indexat):
few-shot (exemple alese prin RAG) vs model fine-tuned cu LoRA, plus simularea KPI
manual vs agentic.

    python scripts/evaluate.py                                    # few-shot pe Groq (modelul din .env)
    python scripts/evaluate.py --models fewshot:ollama:llama3.2 lora:ollama:triaj-lora
    python scripts/evaluate.py --models fewshot:groq:openai/gpt-oss-20b fewshot:ollama:llama3.2 lora:ollama:triaj-lora

Comparatia corecta few-shot vs LoRA e pe ACELASI model de baza (ex. llama3.2 3B):
  fewshot:ollama:llama3.2   = modelul de baza + 3 exemple similare in prompt
  lora:ollama:triaj-lora    = acelasi model, antrenat LoRA pe cele 400 de tichete, fara exemple
Ambele vad aceleasi 400 de tichete etichetate: unul prin RAG, celalalt prin antrenare.

Iesiri in eval/results/: classification_latest.json, kpi_simulation_latest.json,
predictions_<model>.csv, REPORT.md
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent import retrieval  # noqa: E402
from agent.classifier import classify  # noqa: E402
from agent.config import CATEGORY_TO_TEAM, EVAL_DIR, GROQ_MODEL, PRIORITIES, SIM, TEST_CSV  # noqa: E402
from agent.llm import get_chat_model, usage_from  # noqa: E402
from agent.lora_format import LORA_SYSTEM, ticket_text  # noqa: E402
from agent.router import decide  # noqa: E402
from agent.schemas import LabelOnly  # noqa: E402


def predict_fewshot(row, provider, model):
    text = ticket_text(row)
    similar = retrieval.history_retriever.invoke(text)
    t0 = time.perf_counter()
    r = classify(text, similar, [], provider=provider, model=model)
    lat = (time.perf_counter() - t0) * 1000
    c = r.classification
    return {
        "pred_priority": c.priority if c else None, "pred_category": c.category if c else None,
        "pred_team": c.suggested_team if c else None, "confidence": c.confidence if c else None,
        "decision": decide(c).status, "rule": decide(c).rule,
        "latency_ms": lat, "tokens": sum(u.prompt_tokens + u.completion_tokens for u in r.usages),
        "cost_usd": sum(u.cost_usd for u in r.usages), "attempts": r.attempts,
    }


def predict_lora(row, provider, model):
    llm = get_chat_model(provider, model, temperature=0.0)
    t0 = time.perf_counter()
    msg = llm.invoke([SystemMessage(LORA_SYSTEM), HumanMessage(ticket_text(row))])
    lat = (time.perf_counter() - t0) * 1000
    u = usage_from(msg, provider, model, "eval", lat)
    try:
        c = LabelOnly(**json.loads(msg.content))
    except Exception:
        c = None
    return {
        "pred_priority": c.priority if c else None, "pred_category": c.category if c else None,
        "pred_team": c.suggested_team if c else None, "confidence": None, "decision": None, "rule": None,
        "latency_ms": lat, "tokens": u.prompt_tokens + u.completion_tokens, "cost_usd": u.cost_usd, "attempts": 1,
    }


def metrics(df, name, approach):
    y, p = df["true_priority"], df["pred_priority"].fillna("INVALID")
    lab = PRIORITIES
    m = {
        "name": name, "approach": approach,
        "priority_accuracy": round(accuracy_score(y, p), 3),
        "priority_macro_f1": round(f1_score(y, p, labels=lab, average="macro", zero_division=0), 3),
        "category_accuracy": round(accuracy_score(df["true_category"], df["pred_category"].fillna("INVALID")), 3),
        "team_accuracy": round(accuracy_score(df["true_team"], df["pred_team"].fillna("INVALID")), 3),
        "exact_match": round(((y == p) & (df["true_category"] == df["pred_category"])).mean(), 3),
        "invalid_pct": round(100 * df["pred_priority"].isna().mean(), 1),
        "latency_ms_p50": round(statistics.median(df["latency_ms"]), 0),
        "tokens_per_ticket": round(df["tokens"].mean(), 0),
        "cost_per_1000_usd": round(df["cost_usd"].mean() * 1000, 4),
        "confusion_priority": confusion_matrix(y, p, labels=lab).tolist(),
        # P1 reale care au primit alta prioritate SI au fost rutate fara om = riscul real
        "p1_missed_without_human": None,
    }
    if df["decision"].notna().any():
        m["p1_missed_without_human"] = int(((y == "P1") & (p != "P1") & (df["decision"] == "auto_routed")).sum())
        m["human_intervention_pct"] = round(100 * (df["decision"] == "pending_approval").mean(), 1)
        m["auto_resolution_pct"] = round(100 * (df["decision"] == "auto_routed").mean(), 1)
    return m


def simulate(df, name):
    """MTTR simulat. Pornim de la timpul REAL de rezolutie din dataset (proces manual) si
    inlocuim doar partea de triaj + re-rutare cu ce face agentul."""
    rows_m, rows_a = [], []
    for _, r in df.iterrows():
        p = r["true_priority"]
        m_triage = SIM["manual_triage_hours"][p]
        m_reroute = SIM["manual_misroute_rate"] * SIM["reroute_penalty_hours"][p]
        work = max(r["resolution_hours"] - m_triage - m_reroute, 0.1)      # lucrul efectiv, fara triaj
        wrong_team = r["pred_team"] != r["true_team"]
        if r["decision"] == "auto_routed":
            a_triage = r["latency_ms"] / 3_600_000
            a_misroute = 1.0 if wrong_team else 0.0
        else:  # om cu context pregatit; prinde o parte din greseli
            a_triage = SIM["review_hours"][p]
            a_misroute = (1 - SIM["review_catch_rate"]) if wrong_team else 0.0
        rows_m.append((m_triage, SIM["manual_misroute_rate"], r["resolution_hours"], p))
        rows_a.append((a_triage, a_misroute, work + a_triage + a_misroute * SIM["reroute_penalty_hours"][p], p))

    def agg(rows, scenario, human, auto):
        return {"scenario": scenario, "time_to_route_h": round(statistics.mean(x[0] for x in rows), 3),
                "misroute_pct": round(100 * statistics.mean(x[1] for x in rows), 1),
                "mttr_h": round(statistics.mean(x[2] for x in rows), 2),
                "human_decisions_pct": human, "auto_resolution_pct": auto}

    esc = round(100 * (df["decision"] == "pending_approval").mean(), 1)
    by_prio = [{"priority": p,
                "manual_mttr_h": round(statistics.mean(x[2] for x in rows_m if x[3] == p), 2),
                "agentic_mttr_h": round(statistics.mean(x[2] for x in rows_a if x[3] == p), 2)}
               for p in PRIORITIES if any(x[3] == p for x in rows_m)]
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "based_on_model": name,
            "assumptions": SIM, "rows": [agg(rows_m, "Manual (baseline)", 100.0, 0.0),
                                         agg(rows_a, "Agentic", esc, round(100 - esc, 1))],
            "by_priority": by_prio}


def report(cls, sim):
    lines = [f"# Rezultate evaluare — {cls['generated_at'][:16]}", "",
             f"Set de test: {cls['test_size']} tichete (nevăzute la indexare/antrenare).", "",
             "| Model | Prioritate acc. | Prioritate macro-F1 | Categorie acc. | Echipă acc. | JSON invalid % | Intervenție umană % | P1 ratate fără om | Latență p50 (ms) | Tokeni/tichet | Cost/1000 ($) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in cls["models"]:
        lines.append(f"| {m['name']} | {m['priority_accuracy']} | {m['priority_macro_f1']} | {m['category_accuracy']} | "
                     f"{m['team_accuracy']} | {m['invalid_pct']} | {m.get('human_intervention_pct', '—')} | "
                     f"{m['p1_missed_without_human'] if m['p1_missed_without_human'] is not None else '—'} | {m['latency_ms_p50']:.0f} | {m['tokens_per_ticket']:.0f} | {m['cost_per_1000_usd']} |")
    if sim:
        lines += ["", f"## Manual vs agentic (simulare, model: {sim['based_on_model']})", "",
                  "| Scenariu | Timp până la rutare (h) | Rutări greșite % | MTTR (h) | Decizii umane % | Auto-rezolvare % |",
                  "|---|---|---|---|---|---|"]
        for r in sim["rows"]:
            lines.append(f"| {r['scenario']} | {r['time_to_route_h']} | {r['misroute_pct']} | {r['mttr_h']} | "
                         f"{r['human_decisions_pct']} | {r['auto_resolution_pct']} |")
        lines += ["", "| Prioritate | MTTR manual (h) | MTTR agentic (h) |", "|---|---|---|"]
        lines += [f"| {b['priority']} | {b['manual_mttr_h']} | {b['agentic_mttr_h']} |" for b in sim["by_priority"]]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=[f"fewshot:groq:{GROQ_MODEL}"],
                    help="approach:provider:model, approach = fewshot | lora")
    ap.add_argument("--limit", type=int, default=None, help="doar primele N tichete (test rapid)")
    ap.add_argument("--sleep", type=float, default=0.0, help="pauza intre apeluri (rate limit)")
    args = ap.parse_args()

    test = pd.read_csv(TEST_CSV)
    if args.limit:
        test = test.head(args.limit)
    retrieval.ensure_index()
    os.makedirs(EVAL_DIR, exist_ok=True)

    results, sim = [], None
    for spec in args.models:
        approach, provider, model = spec.split(":", 2)
        name = f"{'few-shot RAG' if approach == 'fewshot' else 'LoRA'} · {provider}:{model}"
        fn = predict_fewshot if approach == "fewshot" else predict_lora
        preds = []
        for i, row in enumerate(test.to_dict("records"), 1):
            preds.append(fn(row, provider, model))
            print(f"\r{name}: {i}/{len(test)}", end="", flush=True)
            time.sleep(args.sleep)
        print()
        df = pd.concat([test.reset_index(drop=True), pd.DataFrame(preds)], axis=1)
        df.to_csv(os.path.join(EVAL_DIR, f"predictions_{approach}_{provider}_{model.replace('/', '_')}.csv"), index=False)
        m = metrics(df, name, approach)
        results.append(m)
        print(f"  prioritate acc={m['priority_accuracy']} macroF1={m['priority_macro_f1']} "
              f"categorie acc={m['category_accuracy']} invalid={m['invalid_pct']}%")
        if approach == "fewshot" and sim is None:
            sim = simulate(df, name)

    cls = {"generated_at": datetime.now().isoformat(timespec="seconds"), "test_size": len(test),
           "labels": PRIORITIES, "teams": CATEGORY_TO_TEAM, "models": results}
    with open(os.path.join(EVAL_DIR, "classification_latest.json"), "w", encoding="utf-8") as f:
        json.dump(cls, f, ensure_ascii=False, indent=2)
    if sim:
        with open(os.path.join(EVAL_DIR, "kpi_simulation_latest.json"), "w", encoding="utf-8") as f:
            json.dump(sim, f, ensure_ascii=False, indent=2)
    with open(os.path.join(EVAL_DIR, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write(report(cls, sim))
    print(f"\nRezultate in {EVAL_DIR} (REPORT.md, *_latest.json)")


if __name__ == "__main__":
    main()
