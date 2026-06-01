from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_writer_context_respects_token_budget_and_keeps_canon(tmp_path) -> None:
    from app.domain import ChapterSummary, Character, TimelineEvent, WorldRule
    from app.memory.store import FlashNovelStore

    store = FlashNovelStore(tmp_path / "flashnovel.sqlite3", tmp_path / "artifacts")
    store.initialize()
    story = store.create_story("预算测试", "核心设定很短", story_id="story_budget")
    workspace = store.create_workspace(story.id, workspace_id=story.id)
    store.save_character(
        Character(
            story_id=story.id,
            workspace_id=workspace.id,
            name="林舟",
            role="主角",
            description="旧书店店员",
        )
    )
    store.save_world_rule(
        WorldRule(
            story_id=story.id,
            workspace_id=workspace.id,
            category="premise",
            rule="所有预言都必须付出代价。",
        )
    )
    for chapter in range(1, 8):
        store.save_chapter_summary(
            ChapterSummary(
                story_id=story.id,
                workspace_id=workspace.id,
                chapter=chapter,
                title=f"第{chapter}章",
                summary=("很长的摘要" * 80) + str(chapter),
                key_events=[("很长的事件" * 40) + str(chapter)],
            )
        )
        store.save_timeline_event(
            TimelineEvent(
                story_id=story.id,
                workspace_id=workspace.id,
                chapter=chapter,
                sequence=chapter,
                event=("很长的时间线事件" * 80) + str(chapter),
            )
        )

    full_context = store.get_writer_context(story.id, 8)
    budgeted = store.get_writer_context(story.id, 8, token_budget=700)

    assert full_context["recent_summaries"]
    assert full_context["timeline"]
    assert budgeted["story"]["story_id"] == story.id
    assert budgeted["characters"][0]["name"] == "林舟"
    assert budgeted["world_rules"][0]["rule"] == "所有预言都必须付出代价。"
    assert len(budgeted["recent_summaries"]) < len(full_context["recent_summaries"])
    assert len(budgeted["timeline"]) < len(full_context["timeline"])
    assert budgeted["_context_budget"]["token_budget"] == 700
    assert budgeted["_context_budget"]["estimated_tokens"] <= 700
    assert budgeted["_context_budget"]["dropped_counts"]["recent_summaries"] > 0


def test_service_requeues_running_run_after_restart(tmp_path) -> None:
    from app.api.dto import CreateRunRequest, CreateStoryRequest
    from app.runtime.service import FlashNovelService

    service = FlashNovelService(data_dir=str(tmp_path))
    story = service.create_story(CreateStoryRequest(title="恢复测试", premise="重启后继续"))
    run = service.create_run(
        CreateRunRequest(story_id=str(story["story_id"]), prompt="继续写", max_chapters=1)
    )
    service.store.update_run_status(str(run["run_id"]), "running")

    recovered = FlashNovelService(data_dir=str(tmp_path))
    restored = recovered.get_run(str(run["run_id"]))

    assert restored["status"] == "queued"
    assert recovered.registry.is_busy(str(run["run_id"]))
    events = recovered.get_run_events(str(run["run_id"]))
    assert any(item["type"] == "run.recovered" for item in events)


def test_service_recovers_awaiting_confirmation_checkpoint_without_requeue(tmp_path) -> None:
    from app.api.dto import CreateRunRequest, CreateStoryRequest
    from app.runtime.service import FlashNovelService

    service = FlashNovelService(data_dir=str(tmp_path))
    story = service.create_story(CreateStoryRequest(title="确认测试", premise="每五章确认"))
    run = service.create_run(
        CreateRunRequest(story_id=str(story["story_id"]), prompt="继续写", max_chapters=5)
    )
    run_id = str(run["run_id"])
    service.store.save_checkpoint(
        run_id=run_id,
        chapter=5,
        state={"status": "awaiting_confirmation", "next_chapter": 6},
        pending={"status": "awaiting_confirmation", "next_action": "confirm"},
    )
    service.store.update_run_status(run_id, "running")

    recovered = FlashNovelService(data_dir=str(tmp_path))
    restored = recovered.get_run(run_id)

    assert restored["status"] == "awaiting_confirmation"
    assert not recovered.registry.is_busy(run_id)
    confirmed = recovered.confirm_run(run_id)
    assert confirmed.status == "queued"
    assert recovered.registry.is_busy(run_id)


def test_draft_tool_falls_back_to_non_streaming_when_stream_is_empty(tmp_path) -> None:
    from app.llm.client import ChatCompletion, ChatDelta, ChatUsage
    from app.memory.store import FlashNovelStore
    from app.tools.sync_tools import DraftChapterSyncTool

    class EmptyStreamClient:
        def __init__(self) -> None:
            self.complete_calls = 0

        def stream_sync(self, messages, **kwargs):
            _ = messages, kwargs
            yield ChatDelta(done=True)

        def complete_sync(self, messages, **kwargs):
            _ = messages, kwargs
            self.complete_calls += 1
            return ChatCompletion(
                content="这是非流式补救生成的章节正文。",
                raw={"usage": {"total_tokens": 12}},
                model="qwen3.6-plus",
                usage=ChatUsage(prompt_tokens=7, completion_tokens=5, total_tokens=12),
            )

    store = FlashNovelStore(tmp_path / "flashnovel.sqlite3", tmp_path / "artifacts")
    store.initialize()
    story = store.create_story("空流测试", "模型流式为空时补救", story_id="story_empty_stream")
    workspace = store.create_workspace(story.id, workspace_id=story.id)
    run = store.create_run(story_id=story.id, workspace_id=workspace.id, run_id="run_empty_stream")
    client = EmptyStreamClient()
    tool = DraftChapterSyncTool(store, client)

    result = tool.execute(
        {
            "story_id": story.id,
            "run_id": run.id,
            "chapter": 1,
            "context": {},
            "plan": {"title": "第一章"},
        }
    )

    assert result["content"] == "这是非流式补救生成的章节正文。"
    assert result["word_count"] > 0
    assert client.complete_calls == 1
    artifact = result["artifact"]
    assert store.read_artifact_text(artifact.id) == "这是非流式补救生成的章节正文。"
    events = store.list_event_dicts(run_id=run.id)
    usage_events = [item for item in events if item["type"] == "llm.usage"]
    assert usage_events
    assert usage_events[0]["payload"]["model"] == "qwen3.6-plus"
    assert usage_events[0]["payload"]["usage"]["total_tokens"] == 12
