"""Aduce dataset-ul Kaggle "Synthetic ITSM Ticket Dataset" (avii3301, 9.980 tichete) la
schema proiectului si pastreaza un esantion stratificat.

    python scripts/import_kaggle.py                  # 500 tichete: 400 indexate + 100 test
    python scripts/import_kaggle.py --n 300 --test-frac 0.2

Sursa: data/raw/tickets_clean.csv
(https://www.kaggle.com/datasets/avii3301/synthetic-itsm-ticket-dataset)
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent.config import CATEGORY_TO_TEAM, DATA_DIR, TEST_CSV, TICKETS_CSV  # noqa: E402

PRIORITY_MAP = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(DATA_DIR, "raw", "tickets_clean.csv"))
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"Lipseste {args.file}. Descarca dataset-ul de pe Kaggle si pune tickets_clean.csv in data/raw/.")

    df = pd.read_csv(args.file)
    print(f"Citit {len(df)} tichete")

    # doar tichetele rezolvate: au rezolvare (context pentru RAG) si timp real de rezolvare (baseline MTTR)
    df = df[df["status"].isin(["Resolved", "Closed"])].dropna(subset=["resolution", "time_to_resolution_hours"])
    df = df[df["priority"].isin(PRIORITY_MAP) & df["category"].isin(CATEGORY_TO_TEAM)]

    # esantion stratificat pe prioritate x categorie, proportional cu datele reale
    frac = args.n / len(df)
    sample = df.groupby(["priority", "category"]).sample(frac=min(1.0, frac * 1.05), random_state=args.seed)
    sample = sample.sample(n=min(args.n, len(sample)), random_state=args.seed).reset_index(drop=True)

    out = pd.DataFrame({
        "id": sample["ticket_id"],
        "subject": sample["subject"].str.strip(),
        "description": sample["description"].str.strip(),
        "sub_category": sample["sub_category"],
        "true_priority": sample["priority"].map(PRIORITY_MAP),
        "true_category": sample["category"],
        "true_team": sample["category"].map(CATEGORY_TO_TEAM),
        "resolution": sample["resolution"].str.strip(),
        "resolution_hours": sample["time_to_resolution_hours"],
    })

    # split stratificat pe prioritate: fiecare clasa apare si in test
    test = out.groupby("true_priority").sample(frac=args.test_frac, random_state=args.seed)
    train = out.drop(test.index)
    train.to_csv(TICKETS_CSV, index=False)
    test.to_csv(TEST_CSV, index=False)

    print(f"{len(train)} -> {os.path.relpath(TICKETS_CSV)} (istoric: RAG, few-shot, antrenare LoRA)")
    print(f"{len(test)} -> {os.path.relpath(TEST_CSV)} (test, niciodata indexat)")
    print("\nPrioritati:", out["true_priority"].value_counts().sort_index().to_dict())
    print("Categorii:", out["true_category"].value_counts().to_dict())


if __name__ == "__main__":
    main()
