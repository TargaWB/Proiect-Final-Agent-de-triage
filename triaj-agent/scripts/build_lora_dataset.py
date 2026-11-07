"""Construieste datele pentru fine-tuning LoRA, in format chat (messages).

    python scripts/build_lora_dataset.py

Iese: finetune/train.jsonl (cele 400 de tichete indexate) si finetune/test.jsonl (100 de test).
Aceleasi 400 de tichete pe care le vede few-shot-ul prin RAG -> comparatie corecta.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent.config import ROOT, TEST_CSV, TICKETS_CSV  # noqa: E402
from agent.lora_format import chat_example  # noqa: E402

OUT = os.path.join(ROOT, "finetune")

for src, name in ((TICKETS_CSV, "train.jsonl"), (TEST_CSV, "test.jsonl")):
    rows = pd.read_csv(src).to_dict("records")
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(chat_example(r), ensure_ascii=False) + "\n")
    print(f"{len(rows)} exemple -> finetune/{name}")
