"""Compatibility facade methods for FlashNovelStore.

The core store exposes dataclass-oriented persistence methods. Runtime and API
code still use a compact dictionary-oriented surface, so this module installs
that facade without keeping the compatibility layer inside store.py.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping

from app.domain import (
    ChapterPlan,
    ChapterSummary,
    Foreshadow,
    Relationship,
    ReviewIssue,
    ReviewReport,
    StateChange,
    TimelineEvent,
    Workspace,
)
from app.memory.context import apply_context_budget, resolve_token_budget


def _asdict_or_none(value: Any) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _asdict_list(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in values]


def _workspace_for_story(self: FlashNovelStore, story_id: str) -> Workspace:
    workspaces = self.list_workspaces(story_id)
    if workspaces:
        return workspaces[0]
    return self.create_workspace(story_id=story_id, workspace_id=story_id)


def _compat_init(self: FlashNovelStore) -> None:
    self.initialize()


def _compat_get_story_dict(self: FlashNovelStore, story_id: str) -> dict[str, Any]:
    story = self.get_story(story_id)
    if story is None:
        raise KeyError(f"story not found: {story_id}")
    data = asdict(story)
    data["story_id"] = story.id
    data["premise"] = story.description
    data.update(story.metadata)
    return data


def _compat_list_story_dicts(self: FlashNovelStore) -> list[dict[str, Any]]:
    return [_compat_get_story_dict(self, item.id) for item in self.list_stories()]


def _compat_get_workspace_snapshot(self: FlashNovelStore, story_id: str) -> dict[str, Any]:
    story = _compat_get_story_dict(self, story_id)
    workspace = _workspace_for_story(self, story_id)
    latest = _compat_latest_run_for_story(self, story_id)
    return {
        "story": story,
        "workspace": asdict(workspace),
        "latest_run": latest or None,
        "next_chapter": _compat_next_chapter(self, story_id),
    }


def _compat_update_run_status(self: FlashNovelStore, run_id: str, status: str) -> None:
    self.update_run(run_id, status=status)


def _compat_update_run_chapter(self: FlashNovelStore, run_id: str, chapter: int) -> None:
    self.update_run(run_id, current_chapter=chapter)


def _compat_run_dict(self: FlashNovelStore, run_id: str) -> dict[str, Any]:
    run = self.get_run(run_id)
    if run is None:
        raise KeyError(f"run not found: {run_id}")
    data = asdict(run)
    data["run_id"] = run.id
    data.update(run.input)
    return data


def _compat_latest_run_for_story(self: FlashNovelStore, story_id: str) -> dict[str, Any]:
    runs = self.list_runs(story_id=story_id)
    if not runs:
        return {}
    return _compat_run_dict(self, runs[0].id)


def _compat_next_chapter(self: FlashNovelStore, story_id: str) -> int:
    workspace = _workspace_for_story(self, story_id)
    summaries = self.list_chapter_summaries(story_id, workspace.id)
    if not summaries:
        return 1
    return max(item.chapter for item in summaries) + 1


_native_append_event: Any = None


def _compat_append_event(self: FlashNovelStore, *args: Any, **kwargs: Any) -> Any:
    if args and hasattr(args[0], "run_id") and hasattr(args[0], "type"):
        event = args[0]
        return _native_append_event(
            self,
            run_id=event.run_id,
            event_type=event.type,
            node=str(event.payload.get("node", "") if isinstance(event.payload, dict) else ""),
            chapter=event.payload.get("chapter") if isinstance(event.payload, dict) else None,
            payload={"message": event.message, **(event.payload if isinstance(event.payload, dict) else {})},
        )
    if "event_type" in kwargs:
        return _native_append_event(
            self,
            run_id=str(kwargs["run_id"]),
            event_type=str(kwargs["event_type"]),
            node=str(kwargs.get("node", "")),
            chapter=kwargs.get("chapter"),
            payload=kwargs.get("payload") or {},
        )
    return _native_append_event(self, *args, **kwargs)


def _compat_list_events(self: FlashNovelStore, *, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    events = self.list_events(run_id, after_seq=after_seq, limit=limit)
    out = []
    for item in events:
        data = asdict(item)
        data["type"] = item.type
        data["message"] = item.payload.get("message", item.type)
        data["payload"] = item.payload
        out.append(data)
    return out


_native_save_checkpoint: Any = None


def _compat_save_checkpoint(self: FlashNovelStore, *, run_id: str, story_id: str = "", chapter: int, status: str, payload: dict[str, Any]) -> Any:
    _ = story_id
    return _native_save_checkpoint(self, run_id=run_id, chapter=chapter, state={"status": status, **payload}, pending={"status": status})


def _compat_get_writer_context(self: FlashNovelStore, story_id: str, chapter: int, **kwargs: Any) -> dict[str, Any]:
    workspace = _workspace_for_story(self, story_id)
    plan = self.get_chapter_plan(story_id, workspace.id, chapter)
    context = {
        "story": _compat_get_story_dict(self, story_id),
        "workspace": asdict(workspace),
        "chapter": chapter,
        "chapter_plan": _asdict_or_none(plan) or {},
        "characters": _asdict_list(self.list_characters(story_id, workspace.id, status="active")),
        "world_rules": _asdict_list(self.list_world_rules(story_id, workspace.id, status="active")),
        "locations": _asdict_list(self.list_locations(story_id, workspace.id, status="active")),
        "recent_summaries": _asdict_list(self.list_chapter_summaries(story_id, workspace.id, before_chapter=chapter, limit=5)),
        "timeline": _asdict_list(self.list_timeline_events(story_id, workspace.id, through_chapter=chapter - 1, limit=20)),
        "relationships": _asdict_list(self.list_relationships(story_id, workspace.id, status="active")),
        "foreshadows": _asdict_list(self.list_foreshadows(story_id, workspace.id)),
        "state_changes": _asdict_list(self.list_state_changes(story_id, workspace.id, through_chapter=chapter - 1, limit=30)),
        "review_reports": _asdict_list(self.list_review_reports(story_id, workspace.id, through_chapter=chapter - 1, limit=5)),
        "review_issues": _asdict_list(self.list_review_issues(story_id, workspace.id, status="open", through_chapter=chapter - 1, limit=20)),
    }
    return apply_context_budget(context, resolve_token_budget(kwargs.get("token_budget")))


_native_save_chapter_plan: Any = None


def _compat_save_chapter_plan(self: FlashNovelStore, *args: Any, **kwargs: Any) -> Any:
    if args:
        if len(args) == 1 and isinstance(args[0], ChapterPlan):
            return _native_save_chapter_plan(self, args[0])
        return _native_save_chapter_plan(self, *args, **kwargs)
    story_id = str(kwargs["story_id"])
    chapter = int(kwargs["chapter"])
    plan = dict(kwargs.get("plan") or {})
    workspace = _workspace_for_story(self, story_id)
    return _native_save_chapter_plan(
        self,
        ChapterPlan(
            story_id=story_id,
            workspace_id=workspace.id,
            chapter=chapter,
            title=str(plan.get("title", "")),
            summary=str(plan.get("goal", plan.get("summary", ""))),
            beats=[str(x) for x in (plan.get("beats") or [])],
            status="planned",
            metadata=plan,
        ),
    )


def _compat_persist_candidate_memory(self: FlashNovelStore, *, story_id: str, chapter: int, memory: dict[str, Any] | None = None, review: dict[str, Any] | None = None) -> None:
    workspace = _workspace_for_story(self, story_id)
    memory = memory or {}
    self.save_chapter_summary(
        ChapterSummary(
            story_id=story_id,
            workspace_id=workspace.id,
            chapter=chapter,
            title=str(memory.get("title", f"第{chapter}章")),
            summary=str(memory.get("summary", "")),
            key_events=[str(x) for x in (memory.get("key_events") or [])],
            metadata=memory,
        )
    )
    for idx, item in enumerate(memory.get("timeline_events") or [], start=1):
        if not isinstance(item, Mapping):
            continue
        self.save_timeline_event(
            TimelineEvent(
                story_id=story_id,
                workspace_id=workspace.id,
                chapter=chapter,
                sequence=idx,
                event=str(item.get("event", "")),
                participants=[str(x) for x in (item.get("participants") or item.get("characters") or [])],
                location=str(item.get("location", "")),
                metadata=dict(item),
            )
        )
    for item in memory.get("relationships") or memory.get("relationship_changes") or []:
        if not isinstance(item, Mapping):
            continue
        source = str(item.get("source") or item.get("character_a") or "")
        target = str(item.get("target") or item.get("character_b") or "")
        relation = str(item.get("relation") or item.get("relationship") or "")
        if source and target and relation:
            self.save_relationship(Relationship(story_id=story_id, workspace_id=workspace.id, source=source, target=target, relationship=relation, since_chapter=chapter, metadata=dict(item)))
    for item in memory.get("foreshadows") or memory.get("foreshadow_updates") or []:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("key") or item.get("id") or "")
        if key:
            action = str(item.get("action", "plant"))
            self.save_foreshadow(
                Foreshadow(
                    story_id=story_id,
                    workspace_id=workspace.id,
                    key=key,
                    description=str(item.get("description", "")),
                    setup_chapter=chapter,
                    payoff_chapter=chapter if action == "resolve" else None,
                    status="resolved" if action == "resolve" else "open",
                    metadata=dict(item),
                )
            )
    for item in memory.get("state_changes") or []:
        if not isinstance(item, Mapping):
            continue
        self.save_state_change(
            StateChange(
                story_id=story_id,
                workspace_id=workspace.id,
                chapter=chapter,
                entity=str(item.get("entity", "")),
                attribute=str(item.get("field") or item.get("attribute") or ""),
                before=str(item.get("old_value") or item.get("before") or ""),
                after=str(item.get("new_value") or item.get("after") or ""),
                reason=str(item.get("reason", "")),
                metadata=dict(item),
            )
        )
    if review:
        report = self.save_review_report(
            ReviewReport(
                story_id=story_id,
                workspace_id=workspace.id,
                chapter=chapter,
                score=int(review.get("score", 0) or 0),
                summary=str(review.get("summary", "")),
                metadata=review,
            )
        )
        for issue in review.get("issues") or []:
            if isinstance(issue, Mapping):
                self.save_review_issue(
                    ReviewIssue(
                        story_id=story_id,
                        workspace_id=workspace.id,
                        chapter=chapter,
                        report_id=report.id,
                        severity=str(issue.get("severity", "medium")),
                        category=str(issue.get("category", "")),
                        description=str(issue.get("description", "")),
                        status="open",
                        metadata=dict(issue),
                    )
                )


def _compat_get_memory_view(self: FlashNovelStore, story_id: str) -> dict[str, Any]:
    context = _compat_get_writer_context(self, story_id, _compat_next_chapter(self, story_id))
    return {
        "artifact": {"artifacts": [asdict(item) for item in self.list_artifacts(story_id, limit=20)]},
        "canon": {key: context[key] for key in ("characters", "world_rules", "locations")},
        "episodic": {key: context[key] for key in ("recent_summaries", "timeline")},
        "continuity": {key: context[key] for key in ("relationships", "foreshadows", "state_changes", "review_issues")},
    }


def _compat_get_chapter(self: FlashNovelStore, *, story_id: str, chapter: int) -> dict[str, Any]:
    artifacts = self.list_artifacts(story_id, kind="chapter", chapter=chapter, limit=1)
    if not artifacts:
        raise KeyError(f"chapter not found: {chapter}")
    artifact = artifacts[0]
    summary = None
    workspace = _workspace_for_story(self, story_id)
    chapter_summary = self.get_chapter_summary(story_id, workspace.id, chapter)
    if chapter_summary:
        summary = asdict(chapter_summary)
    return {
        "chapter": chapter,
        "content": self.read_artifact_text(artifact.id),
        "summary": summary,
        "artifact": asdict(artifact),
    }
def install_compat(store_cls: type[Any]) -> None:
    global _native_append_event, _native_save_checkpoint, _native_save_chapter_plan

    _native_append_event = store_cls.append_event
    _native_save_checkpoint = store_cls.save_checkpoint
    _native_save_chapter_plan = store_cls.save_chapter_plan

    store_cls.init = _compat_init  # type: ignore[attr-defined]
    store_cls.get_story_dict = _compat_get_story_dict  # type: ignore[attr-defined]
    store_cls.list_story_dicts = _compat_list_story_dicts  # type: ignore[attr-defined]
    store_cls.get_workspace_snapshot = _compat_get_workspace_snapshot  # type: ignore[attr-defined]
    store_cls.update_run_status = _compat_update_run_status  # type: ignore[attr-defined]
    store_cls.update_run_chapter = _compat_update_run_chapter  # type: ignore[attr-defined]
    store_cls.run_dict = _compat_run_dict  # type: ignore[attr-defined]
    store_cls.latest_run_for_story = _compat_latest_run_for_story  # type: ignore[attr-defined]
    store_cls.next_chapter = _compat_next_chapter  # type: ignore[attr-defined]
    store_cls.append_event = _compat_append_event  # type: ignore[method-assign]
    store_cls.list_event_dicts = _compat_list_events  # type: ignore[attr-defined]
    store_cls.save_checkpoint_compat = _compat_save_checkpoint  # type: ignore[attr-defined]
    store_cls.get_writer_context = _compat_get_writer_context  # type: ignore[attr-defined]
    store_cls.save_chapter_plan = _compat_save_chapter_plan  # type: ignore[method-assign]
    store_cls.save_chapter_plan_compat = _compat_save_chapter_plan  # type: ignore[attr-defined]
    store_cls.persist_candidate_memory = _compat_persist_candidate_memory  # type: ignore[attr-defined]
    store_cls.get_memory_view = _compat_get_memory_view  # type: ignore[attr-defined]
    store_cls.get_chapter = _compat_get_chapter  # type: ignore[method-assign]
