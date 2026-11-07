"""Evaluarea RAG-ului: metrici deterministe de retrieval + RAGAS cu un LLM judecator (Groq).

    python scripts/ragas_eval.py                 # 20 de tichete de test
    python scripts/ragas_eval.py --n 40 --no-llm # doar metricile de retrieval, fara judecator

Ce masuram:
- retrieval (fara LLM): cat de des exemplele aduse din ChromaDB au aceeasi categorie /
  prioritate ca tichetul -> daca RAG-ul aduce precedente relevante
- RAGAS faithfulness: motivarea agentului e sustinuta de exemplele primite? (nu inventeaza)
- RAGAS context precision: exemplele relevante sunt primele in lista?
- RAGAS context recall: eticheta corecta e sustinuta de contextul adus?
"""

import argparse
import json
import os
import statistics
import sys
import types
import warnings
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent import retrieval  # noqa: E402
from agent.classifier import classify  # noqa: E402
from agent.config import EVAL_DIR, TEST_CSV  # noqa: E402
from agent.lora_format import ticket_text  # noqa: E402

JUDGE_MODEL = os.environ.get("RAGAS_JUDGE_MODEL", "openai/gpt-oss-120b")


def _ragas_compat():
    """ragas 0.4.x importa un modul scos din langchain-community 0.4 (folosit doar la isinstance)."""
    name = "langchain_community.chat_models.vertexai"
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            m = types.ModuleType(name)
            m.ChatVertexAI = type("ChatVertexAI", (), {})
            sys.modules[name] = m


def context_doc(d) -> str:
    m = d.metadata
    return (f"[{m['id']}] {d.page_content} | prioritate reala: {m['priority']}, categorie: {m['category']}, "
            f"echipa: {m['team']}. Rezolvare: {m.get('resolution', '')}")


def run_samples(test: pd.DataFrame, with_llm: bool):
    samples, retr = [], []
    for row in test.to_dict("records"):
        text = ticket_text(row)
        docs = retrieval.history_retriever.invoke(text)
        cats = [d.metadata["category"] == row["true_category"] for d in docs]
        prios = [d.metadata["priority"] == row["true_priority"] for d in docs]
        retr.append({"cat_hit": any(cats), "cat_prec": sum(cats) / len(cats), "prio_prec": sum(prios) / len(prios),
                     "top1_distance": docs[0].metadata["distance"]})
        if with_llm:
            c = classify(text, docs, []).classification
            answer = (f"Prioritate {c.priority}, categorie {c.category}, echipa {c.suggested_team}. {c.reasoning}"
                      if c else "Clasificare invalida.")
            samples.append({"user_input": text, "retrieved_contexts": [context_doc(d) for d in docs],
                            "response": answer,
                            "reference": f"Prioritate {row['true_priority']}, categorie {row['true_category']}, "
                                         f"echipa {row['true_team']}."})
        print(f"\r{len(retr)}/{len(test)}", end="", flush=True)
    print()
    return samples, retr


def run_ragas(samples, judge=None):
    _ragas_compat()
    warnings.filterwarnings("ignore")
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall
    from ragas.run_config import RunConfig

    if judge is None:
        from langchain_groq import ChatGroq
        judge = ChatGroq(model=JUDGE_MODEL, temperature=0, reasoning_effort="low", max_retries=3)
    result = evaluate(EvaluationDataset.from_list(samples),
                      metrics=[Faithfulness(), LLMContextPrecisionWithReference(), LLMContextRecall()],
                      llm=LangchainLLMWrapper(judge), run_config=RunConfig(max_workers=2, timeout=120),
                      show_progress=True)
    df = result.to_pandas()
    cols = [c for c in ("faithfulness", "llm_context_precision_with_reference", "context_recall") if c in df]
    return {c: round(float(df[c].mean()), 3) for c in cols}, df


def main(argv=None, judge=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args(argv)

    test = pd.read_csv(TEST_CSV).sample(n=args.n, random_state=7)
    retrieval.ensure_index()
    samples, retr = run_samples(test, with_llm=not args.no_llm)

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"), "n": len(test),
        "judge": None if args.no_llm else JUDGE_MODEL,
        "retrieval": {
            "category_hit@3": round(statistics.mean(r["cat_hit"] for r in retr), 3),
            "category_precision@3": round(statistics.mean(r["cat_prec"] for r in retr), 3),
            "priority_precision@3": round(statistics.mean(r["prio_prec"] for r in retr), 3),
            "mean_top1_distance": round(statistics.mean(r["top1_distance"] for r in retr), 3),
        },
    }
    if samples:
        out["ragas"], df = run_ragas(samples, judge)
        os.makedirs(EVAL_DIR, exist_ok=True)
        df.to_csv(os.path.join(EVAL_DIR, "ragas_samples.csv"), index=False)
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(os.path.join(EVAL_DIR, "ragas_latest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
