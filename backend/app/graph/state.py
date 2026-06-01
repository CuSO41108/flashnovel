from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    run_id: str
    story_id: str
    seed_prompt: str
    chapter: int
    chapters_done_in_batch: int
    max_chapters: int
    context: dict[str, Any]
    plan: dict[str, Any]
    draft: str
    candidate_memory: dict[str, Any]
    consistency: dict[str, Any]
    review: dict[str, Any]
    rewrite_count: int
    status: str
    next_action: str
    error: str
