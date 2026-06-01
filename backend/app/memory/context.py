"""Context budget helpers for writer context assembly."""

from __future__ import annotations

import json
import os
from typing import Any


def estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if not text:
        return 0
    ascii_count = 0
    tokens = 0
    for ch in text:
        if ord(ch) < 128:
            ascii_count += 1
        else:
            tokens += 1
    tokens += (ascii_count + 3) // 4
    return max(tokens, 1)


def resolve_token_budget(value: int | None) -> int:
    raw: Any = value if value and value > 0 else os.environ.get("FLASHNOVEL_CONTEXT_BUDGET", "")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def apply_context_budget(context: dict[str, Any], token_budget: int) -> dict[str, Any]:
    if token_budget <= 0:
        return context

    list_keys = [
        "recent_summaries",
        "review_issues",
        "foreshadows",
        "relationships",
        "state_changes",
        "timeline",
        "review_reports",
    ]
    out = dict(context)
    original_counts = {key: len(out.get(key) or []) for key in list_keys}
    for key in list_keys:
        out[key] = []

    included_counts = {key: 0 for key in list_keys}
    dropped_counts = dict(original_counts)

    for key in list_keys:
        for item in context.get(key) or []:
            candidate = dict(out)
            candidate[key] = [*out[key], item]
            if estimate_tokens(candidate) > token_budget:
                continue
            out[key].append(item)
            included_counts[key] += 1
            dropped_counts[key] -= 1

    out["_context_budget"] = {
        "strategy": "priority_trim",
        "token_budget": token_budget,
        "estimated_tokens": estimate_tokens(out),
        "included_counts": included_counts,
        "dropped_counts": dropped_counts,
    }
    return out
