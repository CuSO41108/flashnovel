"""Novel generation tool chain."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Mapping
from typing import Any

from app.llm.prompts import (
    CHECK_CONSISTENCY_PROMPT,
    DRAFT_CHAPTER_PROMPT,
    EXTRACT_MEMORY_PROMPT,
    PLAN_CHAPTER_PROMPT,
    REVIEW_CHAPTER_PROMPT,
    REWRITE_CHAPTER_PROMPT,
)
from app.tools.base import Tool, ToolContext, ToolResult, complete_text


MAX_REWRITES = 2


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            return json.loads(stripped[start : end + 1])
    raise ValueError("LLM response did not contain valid JSON")


def _as_dict(value: Any, *, fallback_key: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {fallback_key: value}


def _normalise_review_verdict(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"accept", "accepted", "pass", "passed", "ok"}:
        return "accept"
    if text in {"rewrite", "revise", "needs_rewrite", "fail", "failed"}:
        return "rewrite"
    return "rewrite"


async def _append_event(
    tool: Tool,
    context: ToolContext,
    *,
    story_id: str,
    chapter: int,
    event_type: str,
    payload: Mapping[str, Any],
) -> Any:
    if not context.run_id or context.store is None:
        return None
    append_event = getattr(context.store, "append_event", None)
    if append_event is None:
        return None

    try:
        from app.runtime.events import RuntimeEvent

        result = append_event(
            RuntimeEvent(
                run_id=context.run_id,
                type=event_type,
                message=event_type,
                payload={"story_id": story_id, "chapter": chapter, **dict(payload)},
            )
        )
    except TypeError:
        # TODO(store): if append_event does not accept RuntimeEvent, support
        # keyword arguments: run_id, story_id, chapter, event_type, payload.
        result = append_event(
            run_id=context.run_id,
            story_id=story_id,
            chapter=chapter,
            event_type=event_type,
            payload=dict(payload),
        )
    if asyncio.iscoroutine(result):
        return await result
    return result


class NovelContextTool(Tool):
    name = "novel_context"
    description = "Build the writer context package for a story chapter."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        token_budget: int | None = None,
        include_recent_chapters: int = 3,
        **filters: Any,
    ) -> ToolResult:
        # TODO(store): get_writer_context should accept story_id, chapter,
        # token_budget, include_recent_chapters, and optional filters.
        writer_context = await self.call_store(
            context,
            "get_writer_context",
            story_id=story_id,
            chapter=chapter,
            token_budget=token_budget,
            include_recent_chapters=include_recent_chapters,
            **filters,
        )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.novel_context",
            payload={"token_budget": token_budget},
        )
        return ToolResult.success(self.name, context=writer_context)


class PlanChapterTool(Tool):
    name = "plan_chapter"
    description = "Create and persist a structured chapter plan."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        writer_context: Any | None = None,
        context_data: Any | None = None,
        chapter_goal: str = "",
        seed_prompt: str = "",
        temperature: float = 0.3,
        **_: Any,
    ) -> ToolResult:
        llm = self.require_llm(context)
        resolved_context = writer_context if writer_context is not None else context_data or {}
        messages = PLAN_CHAPTER_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            chapter_goal=chapter_goal or seed_prompt or "延续主线并推进本章关键冲突。",
            context_json=_json_text(resolved_context),
        )
        content = await complete_text(
            llm,
            messages,
            temperature=temperature,
            response_format=PLAN_CHAPTER_PROMPT.response_format,
        )
        plan = _as_dict(_json_from_text(content), fallback_key="plan")

        # TODO(store): save_chapter_plan should persist the plan for later
        # draft/review nodes.
        saved = await self.call_store(
            context,
            "save_chapter_plan",
            story_id=story_id,
            chapter=chapter,
            plan=plan,
        )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.plan_chapter",
            payload={"plan": plan},
        )
        return ToolResult.success(self.name, plan=plan, saved=saved)


class DraftChapterTool(Tool):
    name = "draft_chapter"
    description = "Draft chapter prose from context and plan."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        writer_context: Any | None = None,
        context_data: Any | None = None,
        plan: Any,
        seed_prompt: str = "",
        draft_instructions: str = "",
        temperature: float = 0.7,
        **_: Any,
    ) -> ToolResult:
        llm = self.require_llm(context)
        resolved_context = writer_context if writer_context is not None else context_data or {}
        messages = DRAFT_CHAPTER_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            plan_json=_json_text(plan),
            context_json=_json_text(resolved_context),
            draft_instructions=draft_instructions or seed_prompt or "输出完整章节正文，避免提纲式描述。",
        )
        draft = await complete_text(llm, messages, temperature=temperature)

        # TODO(store): save_artifact should accept kind/content/metadata for
        # draft, rewrite, review, and final chapter artifacts.
        artifact = await self.call_store(
            context,
            "save_artifact",
            story_id=story_id,
            run_id=context.run_id or "",
            chapter=chapter,
            kind="draft",
            content=draft,
            metadata={"plan": plan, "rewrite_count": 0},
        )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.draft_chapter",
            payload={"artifact": artifact},
        )
        return ToolResult.success(
            self.name,
            draft=draft,
            content=draft,
            artifact=artifact,
            rewrite_count=0,
            max_rewrites=MAX_REWRITES,
        )


class ExtractMemoryTool(Tool):
    name = "extract_memory"
    description = "Extract candidate memory items from a chapter draft."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        draft_text: str | None = None,
        draft: str | None = None,
        temperature: float = 0.2,
        **_: Any,
    ) -> ToolResult:
        llm = self.require_llm(context)
        resolved_draft = draft_text if draft_text is not None else draft or ""
        messages = EXTRACT_MEMORY_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            draft_text=resolved_draft,
        )
        content = await complete_text(
            llm,
            messages,
            temperature=temperature,
            response_format=EXTRACT_MEMORY_PROMPT.response_format,
        )
        payload = _json_from_text(content)
        if isinstance(payload, Mapping):
            memory = dict(payload)
            candidates = list(memory.get("candidates") or [])
        elif isinstance(payload, list):
            memory = {"candidates": payload}
            candidates = payload
        else:
            memory = {"summary": str(payload), "candidates": [{"summary": str(payload), "type": "note"}]}
            candidates = [{"summary": str(payload), "type": "note"}]

        # TODO(store): save_candidate_memory should persist unconfirmed memory
        # until commit_chapter promotes it.
        if hasattr(context.store, "save_candidate_memory"):
            saved = await self.call_store(
                context,
                "save_candidate_memory",
                story_id=story_id,
                chapter=chapter,
                items=candidates,
                memory=memory,
            )
        else:
            saved = await self.call_store(
                context,
                "save_artifact",
                story_id=story_id,
                run_id=context.run_id or "",
                chapter=chapter,
                kind="memory_candidate",
                content=_json_text(memory),
                metadata={"candidate_count": len(candidates)},
            )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.extract_memory",
            payload={"candidate_count": len(candidates)},
        )
        return ToolResult.success(self.name, memory=memory, candidates=candidates, saved=saved)


class CheckConsistencyTool(Tool):
    name = "check_consistency"
    description = "Check a draft against writer context for continuity issues."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        writer_context: Any | None = None,
        context_data: Any | None = None,
        draft_text: str | None = None,
        draft: str | None = None,
        temperature: float = 0.1,
        **_: Any,
    ) -> ToolResult:
        llm = self.require_llm(context)
        resolved_context = writer_context if writer_context is not None else context_data or {}
        resolved_draft = draft_text if draft_text is not None else draft or ""
        messages = CHECK_CONSISTENCY_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            context_json=_json_text(resolved_context),
            draft_text=resolved_draft,
        )
        content = await complete_text(
            llm,
            messages,
            temperature=temperature,
            response_format=CHECK_CONSISTENCY_PROMPT.response_format,
        )
        report = _as_dict(_json_from_text(content), fallback_key="notes")
        verdict = str(report.get("verdict") or "rewrite").lower()
        if verdict not in {"pass", "rewrite"}:
            verdict = "rewrite"

        artifact = await self.call_store(
            context,
            "save_artifact",
            story_id=story_id,
            run_id=context.run_id or "",
            chapter=chapter,
            kind="consistency_report",
            content=_json_text(report),
            metadata={"verdict": verdict},
        )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.check_consistency",
            payload={"verdict": verdict},
        )
        return ToolResult.success(self.name, report=report, verdict=verdict, artifact=artifact)


class ReviewChapterTool(Tool):
    name = "review_chapter"
    description = "Review a chapter and return rewrite boundary information."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        plan: Any,
        draft_text: str | None = None,
        draft: str | None = None,
        consistency_report: Any | None = None,
        consistency: Any | None = None,
        rewrite_count: int = 0,
        max_rewrites: int = MAX_REWRITES,
        temperature: float = 0.2,
        **_: Any,
    ) -> ToolResult:
        llm = self.require_llm(context)
        resolved_draft = draft_text if draft_text is not None else draft or ""
        resolved_consistency = consistency_report if consistency_report is not None else consistency or {}
        messages = REVIEW_CHAPTER_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            rewrite_count=rewrite_count,
            max_rewrites=max_rewrites,
            plan_json=_json_text(plan),
            consistency_json=_json_text(resolved_consistency),
            draft_text=resolved_draft,
        )
        content = await complete_text(
            llm,
            messages,
            temperature=temperature,
            response_format=REVIEW_CHAPTER_PROMPT.response_format,
        )
        report = _as_dict(_json_from_text(content), fallback_key="review")
        requested_verdict = _normalise_review_verdict(report.get("verdict"))
        can_rewrite = requested_verdict == "rewrite" and rewrite_count < max_rewrites
        verdict = requested_verdict
        if requested_verdict == "rewrite" and not can_rewrite:
            verdict = "rewrite_limit_reached"

        enriched_report = {
            **report,
            "verdict": verdict,
            "requested_verdict": requested_verdict,
            "rewrite_count": rewrite_count,
            "max_rewrites": max_rewrites,
            "can_rewrite": can_rewrite,
        }

        # TODO(store): save_review_report should persist the review payload and
        # boundary values so graph/runtime can decide whether to rewrite.
        if hasattr(context.store, "save_review_report"):
            saved = await self.call_store(
                context,
                "save_review_report",
                story_id=story_id,
                chapter=chapter,
                report=enriched_report,
            )
        else:
            saved = await self.call_store(
                context,
                "save_artifact",
                story_id=story_id,
                run_id=context.run_id or "",
                chapter=chapter,
                kind="review",
                content=_json_text(enriched_report),
                metadata={"verdict": verdict, "rewrite_count": rewrite_count},
            )
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.review_chapter",
            payload={
                "verdict": verdict,
                "rewrite_count": rewrite_count,
                "can_rewrite": can_rewrite,
            },
        )
        return ToolResult.success(
            self.name,
            report=enriched_report,
            saved=saved,
            verdict=verdict,
            rewrite_count=rewrite_count,
            max_rewrites=max_rewrites,
            can_rewrite=can_rewrite,
        )


class RewriteChapterTool(Tool):
    name = "rewrite_chapter"
    description = "Rewrite a chapter, capped by max_rewrites."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        writer_context: Any | None = None,
        context_data: Any | None = None,
        draft_text: str | None = None,
        draft: str | None = None,
        review_report: Any | None = None,
        review: Any | None = None,
        rewrite_count: int,
        max_rewrites: int = MAX_REWRITES,
        temperature: float = 0.55,
        **_: Any,
    ) -> ToolResult:
        resolved_draft = draft_text if draft_text is not None else draft or ""
        if rewrite_count >= max_rewrites:
            return ToolResult.success(
                self.name,
                draft=resolved_draft,
                content=resolved_draft,
                verdict="rewrite_limit_reached",
                rewrite_count=rewrite_count,
                max_rewrites=max_rewrites,
                can_rewrite=False,
            )

        llm = self.require_llm(context)
        resolved_context = writer_context if writer_context is not None else context_data or {}
        resolved_review = review_report if review_report is not None else review or {}
        next_rewrite_count = rewrite_count + 1
        messages = REWRITE_CHAPTER_PROMPT.render(
            story_id=story_id,
            chapter=chapter,
            rewrite_count=next_rewrite_count,
            max_rewrites=max_rewrites,
            context_json=_json_text(resolved_context),
            draft_text=resolved_draft,
            review_json=_json_text(resolved_review),
        )
        rewritten = await complete_text(llm, messages, temperature=temperature)
        artifact = await self.call_store(
            context,
            "save_artifact",
            story_id=story_id,
            run_id=context.run_id or "",
            chapter=chapter,
            kind="chapter_rewrite",
            content=rewritten,
            metadata={
                "review": resolved_review,
                "rewrite_count": next_rewrite_count,
                "max_rewrites": max_rewrites,
            },
        )
        can_rewrite_again = next_rewrite_count < max_rewrites
        await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.rewrite_chapter",
            payload={
                "rewrite_count": next_rewrite_count,
                "can_rewrite": can_rewrite_again,
            },
        )
        return ToolResult.success(
            self.name,
            draft=rewritten,
            content=rewritten,
            artifact=artifact,
            verdict="rewritten",
            rewrite_count=next_rewrite_count,
            max_rewrites=max_rewrites,
            can_rewrite=can_rewrite_again,
        )


class CommitChapterTool(Tool):
    name = "commit_chapter"
    description = "Persist the accepted chapter and promote candidate memory."

    async def run(
        self,
        context: ToolContext,
        *,
        story_id: str,
        chapter: int,
        final_text: str | None = None,
        draft: str | None = None,
        plan: Any | None = None,
        review_report: Any | None = None,
        review: Any | None = None,
        candidate_memory: Any | None = None,
        rewrite_count: int = 0,
        **_: Any,
    ) -> ToolResult:
        resolved_text = final_text if final_text is not None else draft or ""
        resolved_review = review_report if review_report is not None else review or {}
        memory = candidate_memory or {}
        if isinstance(memory, Mapping) and "memory" in memory:
            memory = memory["memory"]
        if isinstance(memory, Mapping) and "candidates" in memory and "summary" not in memory:
            memory = {
                **dict(memory),
                "summary": "; ".join(
                    str(item.get("summary", ""))
                    for item in memory.get("candidates", [])
                    if isinstance(item, Mapping)
                ),
            }

        # TODO(store): save_artifact(kind='chapter') is assumed to be the
        # final chapter persistence API until a dedicated save_chapter exists.
        artifact = await self.call_store(
            context,
            "save_artifact",
            story_id=story_id,
            run_id=context.run_id or "",
            chapter=chapter,
            kind="chapter",
            content=resolved_text,
            metadata={
                "plan": plan,
                "review": resolved_review,
                "rewrite_count": rewrite_count,
                "status": "committed",
            },
        )
        # TODO(store): persist_candidate_memory should promote candidate memory
        # extracted for this chapter into canonical/episodic/continuity memory.
        memory_result = await self.call_store(
            context,
            "persist_candidate_memory",
            story_id=story_id,
            chapter=chapter,
            memory=memory,
            review=resolved_review,
        )
        event = await _append_event(
            self,
            context,
            story_id=story_id,
            chapter=chapter,
            event_type="tool.commit_chapter",
            payload={"artifact": artifact, "rewrite_count": rewrite_count},
        )
        return ToolResult.success(
            self.name,
            artifact=artifact,
            memory=memory_result,
            event=event,
            verdict="committed",
            rewrite_count=rewrite_count,
        )


def default_novel_tools() -> dict[str, Tool]:
    tools: list[Tool] = [
        NovelContextTool(),
        PlanChapterTool(),
        DraftChapterTool(),
        ExtractMemoryTool(),
        CheckConsistencyTool(),
        ReviewChapterTool(),
        RewriteChapterTool(),
        CommitChapterTool(),
    ]
    return {tool.name: tool for tool in tools}


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["error"]
    return result.get("value")


class RuntimeToolAdapter:
    """Synchronous adapter expected by RuntimeHost.call_tool."""

    def __init__(self, tool: Tool, store: Any, llm: Any, emit_delta: Any | None = None) -> None:
        self.tool = tool
        self.store = store
        self.llm = llm
        self.emit_delta = emit_delta

    def execute(self, args: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(args)
        run_id = str(payload.pop("run_id", "") or "")
        if self.tool.name == "rewrite_chapter" and "rewrite_count" in payload:
            payload["rewrite_count"] = max(0, int(payload["rewrite_count"] or 0) - 1)
        payload = self._normalise_payload(payload)
        result = _run_sync(self.tool(ToolContext(store=self.store, llm=self.llm, run_id=run_id), **payload))
        if not result.ok:
            raise RuntimeError(result.error or f"tool failed: {self.tool.name}")
        if self.tool.name == "novel_context" and set(result.data) == {"context"}:
            return result.data["context"]
        if self.tool.name == "plan_chapter" and "plan" in result.data:
            return result.data["plan"]
        return result.data

    def _normalise_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "context" in payload and "context_data" not in payload:
            payload["context_data"] = payload.pop("context")
        if "draft" in payload and "draft_text" not in payload:
            payload["draft_text"] = payload["draft"]
        if "review" in payload and "review_report" not in payload:
            payload["review_report"] = payload["review"]
        if "consistency" in payload and "consistency_report" not in payload:
            payload["consistency_report"] = payload["consistency"]
        if "seed_prompt" in payload and "chapter_goal" not in payload and self.tool.name == "plan_chapter":
            payload["chapter_goal"] = payload["seed_prompt"]
        return payload


def build_tool_registry(store: Any, llm: Any, emit_delta: Any | None = None) -> dict[str, RuntimeToolAdapter]:
    return {
        name: RuntimeToolAdapter(tool, store, llm, emit_delta=emit_delta)
        for name, tool in default_novel_tools().items()
    }
