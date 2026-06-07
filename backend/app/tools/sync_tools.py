from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from app.llm.prompts import (
    CHECK_CONSISTENCY_PROMPT,
    DRAFT_CHAPTER_PROMPT,
    EXTRACT_MEMORY_PROMPT,
    PLAN_CHAPTER_PROMPT,
    REVIEW_CHAPTER_PROMPT,
    REWRITE_CHAPTER_PROMPT,
)


MAX_REWRITES = 2


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _json_from_text(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except Exception as exc:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except Exception as nested_exc:
                return {"_parse_error": str(nested_exc), "_raw_text": raw}
        else:
            return {"_parse_error": str(exc), "_raw_text": raw}
    return data if isinstance(data, dict) else {"items": data}


def _messages(template, **kwargs):
    return template.render(kwargs)


def _complete_json(client, template, **kwargs) -> dict[str, Any]:
    result = client.complete_sync(
        _messages(template, **kwargs),
        temperature=kwargs.get("temperature"),
        response_format=template.response_format,
    )
    return _json_from_text(result.content)


def _usage_payload(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    return {key: value for key, value in asdict(usage).items() if value is not None}


class SyncTool:
    tool_name = ""

    def __init__(self, store, client, emit_delta=None) -> None:
        self.store = store
        self.client = client
        self.emit_delta = emit_delta

    def name(self) -> str:
        return self.tool_name

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def emit_usage(self, args: dict[str, Any], result: Any, *, mode: str) -> None:
        usage = _usage_payload(result)
        run_id = str(args.get("run_id", "") or "")
        if not run_id or not usage:
            return
        self.store.append_event(
            run_id=run_id,
            event_type="llm.usage",
            payload={
                "message": f"{self.tool_name} llm usage",
                "tool": self.tool_name,
                "mode": mode,
                "model": getattr(result, "model", None) or getattr(getattr(self.client, "config", None), "model", ""),
                "usage": usage,
                "finish_reason": getattr(result, "finish_reason", None),
            },
        )


class NovelContextSyncTool(SyncTool):
    tool_name = "novel_context"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.store.get_writer_context(
            story_id=str(args["story_id"]),
            chapter=int(args["chapter"]),
            token_budget=int(args.get("token_budget") or 0),
        )


class PlanChapterSyncTool(SyncTool):
    tool_name = "plan_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        story_id = str(args["story_id"])
        chapter = int(args["chapter"])
        context = args.get("context") or {}
        plan = _complete_json(
            self.client,
            PLAN_CHAPTER_PROMPT,
            story_id=story_id,
            chapter=chapter,
            chapter_goal=str(args.get("seed_prompt") or "推进主线并保持连载吸引力"),
            context_json=_json_text(context),
            temperature=0.3,
        )
        normalized = {
            "title": str(plan.get("title") or f"第{chapter}章"),
            "goal": str(plan.get("goal") or plan.get("summary") or "推进主线"),
            "conflict": str(plan.get("conflict") or "角色面临新的压力"),
            "hook": str(plan.get("hook") or "章末留下悬念"),
            "beats": plan.get("beats") or plan.get("required_beats") or [],
            "raw": plan,
        }
        self.store.save_chapter_plan(story_id=story_id, chapter=chapter, plan=normalized)
        self.store.save_artifact(
            story_id=story_id,
            run_id=str(args.get("run_id", "")),
            chapter=chapter,
            kind="prompt",
            extension="json",
            content=_json_text({"tool": self.tool_name, "context": context, "plan": normalized}),
        )
        return normalized


class DraftChapterSyncTool(SyncTool):
    tool_name = "draft_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        story_id = str(args["story_id"])
        run_id = str(args.get("run_id", ""))
        chapter = int(args["chapter"])
        messages = _messages(
            DRAFT_CHAPTER_PROMPT,
            story_id=story_id,
            chapter=chapter,
            plan_json=_json_text(args.get("plan") or {}),
            context_json=_json_text(args.get("context") or {}),
            draft_instructions="输出完整中文章节正文，不要解释，不要写大纲。",
        )
        chunks: list[str] = []
        try:
            for delta in self.client.stream_sync(messages, temperature=0.7):
                if delta.done:
                    break
                if delta.content:
                    chunks.append(delta.content)
                    if self.emit_delta:
                        self.emit_delta(run_id, delta.content, "content")
            content = "".join(chunks).strip()
        except Exception:
            result = self.client.complete_sync(messages, temperature=0.7)
            self.emit_usage(args, result, mode="fallback_after_stream_error")
            content = result.content.strip()
        if not content:
            result = self.client.complete_sync(messages, temperature=0.7)
            self.emit_usage(args, result, mode="fallback_after_empty_stream")
            content = result.content.strip()
        if not content:
            raise RuntimeError(f"chapter {chapter} draft is empty")
        artifact = self.store.save_artifact(story_id=story_id, run_id=run_id, chapter=chapter, kind="draft", content=content)
        return {"content": content, "artifact": artifact, "word_count": len(content)}


class ExtractMemorySyncTool(SyncTool):
    tool_name = "extract_memory"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        story_id = str(args["story_id"])
        chapter = int(args["chapter"])
        draft = str(args.get("draft") or "")
        memory = _complete_json(
            self.client,
            EXTRACT_MEMORY_PROMPT,
            story_id=story_id,
            chapter=chapter,
            draft_text=draft,
            temperature=0.2,
        )
        normalized = {
            "title": str((args.get("plan") or {}).get("title") or memory.get("title") or f"第{chapter}章"),
            "summary": str(memory.get("summary") or ""),
            "key_events": memory.get("key_events") or [],
            "timeline_events": memory.get("timeline_events") or [],
            "relationships": memory.get("relationships") or memory.get("relationship_changes") or [],
            "foreshadows": memory.get("foreshadows") or memory.get("foreshadow_updates") or [],
            "state_changes": memory.get("state_changes") or [],
            "raw": memory,
        }
        self.store.save_artifact(
            story_id=story_id,
            run_id=str(args.get("run_id", "")),
            chapter=chapter,
            kind="llm_raw",
            extension="json",
            content=_json_text({"tool": self.tool_name, "memory": normalized}),
        )
        return normalized


class CheckConsistencySyncTool(SyncTool):
    tool_name = "check_consistency"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        report = _complete_json(
            self.client,
            CHECK_CONSISTENCY_PROMPT,
            story_id=str(args["story_id"]),
            chapter=int(args["chapter"]),
            context_json=_json_text(args.get("context") or {}),
            draft_text=str(args.get("draft") or ""),
            temperature=0.1,
        )
        verdict = str(report.get("verdict") or "pass").lower()
        if verdict not in {"pass", "rewrite"}:
            verdict = "rewrite" if report.get("issues") else "pass"
        report["verdict"] = verdict
        return report


class ReviewChapterSyncTool(SyncTool):
    tool_name = "review_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        rewrite_count = int(args.get("rewrite_count", 0) or 0)
        report = _complete_json(
            self.client,
            REVIEW_CHAPTER_PROMPT,
            story_id=str(args["story_id"]),
            chapter=int(args["chapter"]),
            rewrite_count=rewrite_count,
            max_rewrites=MAX_REWRITES,
            plan_json=_json_text(args.get("plan") or {}),
            consistency_json=_json_text(args.get("consistency") or {}),
            draft_text=str(args.get("draft") or ""),
            temperature=0.2,
        )
        verdict = str(report.get("verdict") or "accept").lower()
        if verdict in {"pass", "accepted", "ok"}:
            verdict = "accept"
        if verdict not in {"accept", "rewrite", "polish"}:
            verdict = "rewrite" if report.get("issues") else "accept"
        if verdict in {"rewrite", "polish"} and rewrite_count >= MAX_REWRITES:
            verdict = "accept"
            report["rewrite_limit_reached"] = True
        report["verdict"] = verdict
        report["rewrite_count"] = rewrite_count
        report["max_rewrites"] = MAX_REWRITES
        return report


class RewriteChapterSyncTool(SyncTool):
    tool_name = "rewrite_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        rewrite_count = int(args.get("rewrite_count", 0) or 0)
        if rewrite_count > MAX_REWRITES:
            return {"content": str(args.get("draft") or ""), "rewrite_count": rewrite_count, "skipped": True}
        content = self.client.complete_sync(
            _messages(
                REWRITE_CHAPTER_PROMPT,
                story_id=str(args["story_id"]),
                chapter=int(args["chapter"]),
                rewrite_count=rewrite_count,
                max_rewrites=MAX_REWRITES,
                context_json=_json_text(args.get("context") or {}),
                draft_text=str(args.get("draft") or ""),
                review_json=_json_text(args.get("review") or {}),
            ),
            temperature=0.55,
        ).content.strip()
        self.store.save_artifact(
            story_id=str(args["story_id"]),
            run_id=str(args.get("run_id", "")),
            chapter=int(args["chapter"]),
            kind="draft",
            content=content,
            metadata={"rewrite_count": rewrite_count},
        )
        return {"content": content, "rewrite_count": rewrite_count}


class CommitChapterSyncTool(SyncTool):
    tool_name = "commit_chapter"

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        story_id = str(args["story_id"])
        run_id = str(args.get("run_id", ""))
        chapter = int(args["chapter"])
        draft = str(args.get("draft") or "")
        review = args.get("review") or {}
        memory = args.get("candidate_memory") or {}
        artifact = self.store.save_artifact(
            story_id=story_id,
            run_id=run_id,
            chapter=chapter,
            kind="chapter",
            content=draft,
            metadata={"review": review, "plan": args.get("plan") or {}},
        )
        self.store.persist_candidate_memory(story_id=story_id, chapter=chapter, memory=memory, review=review)
        self.store.update_run_chapter(run_id, chapter + 1)
        return {"committed": True, "chapter": chapter, "artifact": artifact}


def build_tool_registry(store, client, emit_delta=None) -> dict[str, SyncTool]:
    tools = [
        NovelContextSyncTool(store, client, emit_delta),
        PlanChapterSyncTool(store, client, emit_delta),
        DraftChapterSyncTool(store, client, emit_delta),
        ExtractMemorySyncTool(store, client, emit_delta),
        CheckConsistencySyncTool(store, client, emit_delta),
        ReviewChapterSyncTool(store, client, emit_delta),
        RewriteChapterSyncTool(store, client, emit_delta),
        CommitChapterSyncTool(store, client, emit_delta),
    ]
    return {tool.name(): tool for tool in tools}
