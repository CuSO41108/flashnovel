from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.graph.state import GraphState


MAX_REWRITES = 2


def load_context_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        if runtime.should_abort(state["run_id"]):
            state["status"] = "paused"
            state["next_action"] = "finish"
            return state
        chapter = int(state.get("chapter") or runtime.next_chapter(state["story_id"]))
        state["chapter"] = chapter
        runtime.emit(state["run_id"], "node.started", f"load context for chapter {chapter}", {"chapter": chapter})
        state["context"] = runtime.call_tool(
            "novel_context",
            {
                "story_id": state["story_id"],
                "chapter": chapter,
                "token_budget": int(state.get("context_budget", 0) or 0),
            },
        )
        runtime.emit(state["run_id"], "node.completed", f"context loaded for chapter {chapter}", {"chapter": chapter})
        state["next_action"] = "plan"
        return state

    return _node


def plan_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"plan chapter {chapter}", {"chapter": chapter})
        state["plan"] = runtime.call_tool(
            "plan_chapter",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "seed_prompt": state.get("seed_prompt", ""),
                "context": state.get("context", {}),
            },
        )
        runtime.emit(state["run_id"], "chapter.planned", f"chapter {chapter} planned", {"chapter": chapter})
        state["next_action"] = "draft"
        return state

    return _node


def draft_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"draft chapter {chapter}", {"chapter": chapter})
        result = runtime.call_tool(
            "draft_chapter",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "seed_prompt": state.get("seed_prompt", ""),
                "context": state.get("context", {}),
                "plan": state.get("plan", {}),
            },
        )
        state["draft"] = str(result.get("content", "") or "")
        runtime.emit(
            state["run_id"],
            "chapter.drafted",
            f"chapter {chapter} drafted",
            {"chapter": chapter, "word_count": len(state["draft"])},
        )
        state["next_action"] = "extract"
        return state

    return _node


def extract_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"extract candidate memory for chapter {chapter}", {"chapter": chapter})
        state["candidate_memory"] = runtime.call_tool(
            "extract_memory",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "draft": state.get("draft", ""),
                "plan": state.get("plan", {}),
            },
        )
        runtime.emit(state["run_id"], "node.completed", f"candidate memory extracted for chapter {chapter}", {"chapter": chapter})
        state["next_action"] = "check"
        return state

    return _node


def check_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"check consistency for chapter {chapter}", {"chapter": chapter})
        state["consistency"] = runtime.call_tool(
            "check_consistency",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "draft": state.get("draft", ""),
                "candidate_memory": state.get("candidate_memory", {}),
                "context": state.get("context", {}),
            },
        )
        runtime.emit(state["run_id"], "node.completed", f"consistency checked for chapter {chapter}", {"chapter": chapter})
        state["next_action"] = "review"
        return state

    return _node


def review_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"review chapter {chapter}", {"chapter": chapter})
        state["review"] = runtime.call_tool(
            "review_chapter",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "draft": state.get("draft", ""),
                "plan": state.get("plan", {}),
                "consistency": state.get("consistency", {}),
                "rewrite_count": int(state.get("rewrite_count", 0) or 0),
            },
        )
        verdict = str(state["review"].get("verdict", "accept") or "accept")
        runtime.emit(state["run_id"], "chapter.reviewed", f"chapter {chapter} review: {verdict}", {"chapter": chapter, "verdict": verdict})
        rewrite_count = int(state.get("rewrite_count", 0) or 0)
        if verdict in {"rewrite", "polish"} and rewrite_count < MAX_REWRITES:
            state["next_action"] = "rewrite"
        else:
            state["next_action"] = "commit"
        return state

    return _node


def rewrite_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        rewrite_count = int(state.get("rewrite_count", 0) or 0) + 1
        state["rewrite_count"] = rewrite_count
        runtime.emit(state["run_id"], "node.started", f"rewrite chapter {chapter}", {"chapter": chapter, "rewrite_count": rewrite_count})
        result = runtime.call_tool(
            "rewrite_chapter",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "draft": state.get("draft", ""),
                "review": state.get("review", {}),
                "context": state.get("context", {}),
                "rewrite_count": rewrite_count,
            },
        )
        state["draft"] = str(result.get("content", "") or state.get("draft", ""))
        runtime.emit(state["run_id"], "chapter.rewritten", f"chapter {chapter} rewritten", {"chapter": chapter, "rewrite_count": rewrite_count})
        state["next_action"] = "extract"
        return state

    return _node


def commit_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        chapter = int(state["chapter"])
        runtime.emit(state["run_id"], "node.started", f"commit chapter {chapter}", {"chapter": chapter})
        runtime.call_tool(
            "commit_chapter",
            {
                "story_id": state["story_id"],
                "run_id": state["run_id"],
                "chapter": chapter,
                "draft": state.get("draft", ""),
                "plan": state.get("plan", {}),
                "candidate_memory": state.get("candidate_memory", {}),
                "review": state.get("review", {}),
            },
        )
        state["chapters_done_in_batch"] = int(state.get("chapters_done_in_batch", 0) or 0) + 1
        state["rewrite_count"] = 0
        runtime.emit(state["run_id"], "chapter.committed", f"chapter {chapter} committed", {"chapter": chapter})
        state["next_action"] = "checkpoint"
        return state

    return _node


def checkpoint_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        run_id = state["run_id"]
        story_id = state["story_id"]
        chapter = int(state["chapter"])
        done = int(state.get("chapters_done_in_batch", 0) or 0)
        max_chapters = int(state.get("max_chapters", 5) or 5)
        if runtime.should_abort(run_id):
            runtime.create_checkpoint(run_id, story_id, chapter, "paused")
            state["status"] = "paused"
            state["next_action"] = "finish"
            return state
        if done >= max_chapters:
            runtime.create_checkpoint(run_id, story_id, chapter, "awaiting_confirmation")
            runtime.emit(run_id, "run.awaiting_confirmation", f"completed {done} chapters, awaiting confirmation", {"chapter": chapter, "completed_in_batch": done})
            state["status"] = "awaiting_confirmation"
            state["next_action"] = "finish"
            return state
        state["chapter"] = chapter + 1
        state["next_action"] = "continue"
        return state

    return _node


def finish_node(runtime) -> Callable[[GraphState], GraphState]:
    def _node(state: GraphState) -> GraphState:
        if not state.get("status"):
            state["status"] = "completed"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        return state

    return _node


def route_after_review(state: GraphState) -> str:
    return str(state.get("next_action") or "commit")


def route_after_checkpoint(state: GraphState) -> str:
    action = str(state.get("next_action") or "finish")
    if action == "continue":
        return "load_context"
    return "finish"
