"""Formatul prompt -> raspuns pentru modelul fine-tuned cu LoRA. Acelasi text la antrenare
(scripts/build_lora_dataset.py, notebook-ul Colab) si la evaluare (scripts/evaluate.py)."""

import json

from agent.config import CATEGORY_TO_TEAM

LORA_SYSTEM = (
    "Clasifica tichetul IT. Raspunde doar cu JSON: "
    '{"priority": "P1|P2|P3|P4", "category": "...", "suggested_team": "..."}. '
    "Categorii -> echipa: " + "; ".join(f"{c} -> {t}" for c, t in CATEGORY_TO_TEAM.items())
)


def ticket_text(row: dict) -> str:
    return f"{row['subject']}. {row['description']}"


def target(row: dict) -> str:
    return json.dumps({"priority": row["true_priority"], "category": row["true_category"],
                       "suggested_team": row["true_team"]})


def chat_example(row: dict) -> dict:
    return {"messages": [
        {"role": "system", "content": LORA_SYSTEM},
        {"role": "user", "content": ticket_text(row)},
        {"role": "assistant", "content": target(row)},
    ]}
