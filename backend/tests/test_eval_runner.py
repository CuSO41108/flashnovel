from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_dry_run_writes_prompt_snapshots_and_summary_without_llm(tmp_path) -> None:
    from eval.run_eval import EvalConfig, run_eval

    config = EvalConfig(
        dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
        output_dir=tmp_path / "results",
        systems=("naive_recent_text", "structured_memory_only"),
        limit=1,
        live=False,
        judge=False,
    )

    summary = run_eval(config)

    assert summary["mode"] == "dry-run"
    assert summary["dataset_scope"]["case_count"] == 20
    assert summary["dataset_scope"]["target_chapters"] == 28
    assert summary["execution_scope"]["case_count"] == 1
    assert summary["execution_scope"]["systems"] == [
        "naive_recent_text",
        "structured_memory_only",
    ]
    assert summary["execution_scope"]["coverage_status"] == "partial"
    assert summary["llm_calls"]["attempted_count"] == 0
    assert (
        summary["by_system"]["naive_recent_text"]["hard_metrics"]["run_success_rate"]["status"]
        == "unavailable"
    )

    summary_path = Path(summary["summary_path"])
    report_path = Path(summary["report_path"])
    assert summary_path.is_file()
    assert report_path.is_file()

    saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    first_result = saved_summary["results"][0]
    assert first_result["case_id"] == "fn-multi-001"
    assert first_result["status"] == "dry_run"
    assert Path(first_result["prompt_path"]).is_file()
    assert Path(first_result["chapter_path"]).is_file()
    assert "继续写第6章" in Path(first_result["prompt_path"]).read_text(encoding="utf-8")


def test_live_mode_requires_llm_credentials_before_running(tmp_path, monkeypatch) -> None:
    from eval.run_eval import EvalConfig, run_eval

    for key in (
        "FLASHNOVEL_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.setenv(key, "")

    config = EvalConfig(
        dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
        output_dir=tmp_path / "results",
        systems=("naive_recent_text",),
        limit=1,
        live=True,
        judge=False,
    )

    with pytest.raises(RuntimeError, match="--live requires an API key"):
        run_eval(config)


def test_flashnovel_event_complete_accepts_runtime_node_messages() -> None:
    from eval.run_eval import flashnovel_event_complete

    events = [
        {"type": "node.completed", "payload": {"message": "context loaded for chapter 6"}},
        {"type": "chapter.planned", "payload": {"message": "chapter 6 planned"}},
        {"type": "chapter.drafted", "payload": {"message": "chapter 6 drafted"}},
        {"type": "node.completed", "payload": {"message": "candidate memory extracted for chapter 6"}},
        {"type": "node.completed", "payload": {"message": "consistency checked for chapter 6"}},
        {"type": "chapter.reviewed", "payload": {"message": "chapter 6 review: accept"}},
        {"type": "chapter.committed", "payload": {"message": "chapter 6 committed"}},
    ]

    assert flashnovel_event_complete(events)


def test_runner_records_failed_system_result_and_writes_summary(tmp_path) -> None:
    from eval.run_eval import EvalConfig, EvalClient, run_eval

    class FailingClient(EvalClient):
        def __init__(self) -> None:
            self.calls = 0

        def complete_text(self, prompt, *, temperature=0.7, response_format=None, **kwargs):
            _ = prompt, temperature, response_format, kwargs
            self.calls += 1
            raise RuntimeError("simulated model failure")

    config = EvalConfig(
        dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
        output_dir=tmp_path / "results",
        systems=("naive_recent_text",),
        limit=1,
        live=True,
        judge=False,
    )

    summary = run_eval(config, client_factory=FailingClient)

    assert summary["results"][0]["status"] == "failed"
    assert "simulated model failure" in summary["results"][0]["error"]
    assert (
        summary["by_system"]["naive_recent_text"]["hard_metrics"]["run_success_rate"]["value"]
        == 0.0
    )
    assert Path(summary["summary_path"]).is_file()


def test_dry_run_does_not_fabricate_live_workflow_evidence(tmp_path) -> None:
    from eval.run_eval import EvalConfig, run_eval

    summary = run_eval(
        EvalConfig(
            dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
            output_dir=tmp_path / "results",
            systems=("flashnovel_full",),
            limit=1,
            live=False,
            judge=False,
        )
    )

    result = summary["results"][0]
    assert result["mode"] == "dry-run"
    assert result["event_complete"] is None
    assert result["checkpoint_created"] is None
    assert result["memory_written"] is None
    assert result["target_chapter_count"] == 1
    assert result["generated_chapter_count"] == 0
    assert result["chapter_complete"] is False


def test_flashnovel_event_complete_rejects_missing_required_event() -> None:
    from eval.run_eval import flashnovel_event_complete

    events = [
        {"type": "node.completed", "payload": {"message": "context loaded for chapter 6"}},
        {"type": "chapter.planned", "payload": {"message": "chapter 6 planned"}},
        {"type": "chapter.drafted", "payload": {"message": "chapter 6 drafted"}},
        {"type": "node.completed", "payload": {"message": "candidate memory extracted for chapter 6"}},
        {"type": "node.completed", "payload": {"message": "consistency checked for chapter 6"}},
        {"type": "chapter.reviewed", "payload": {"message": "chapter 6 review: accept"}},
    ]

    assert flashnovel_event_complete(events) is False


def test_flashnovel_event_complete_checks_every_target_chapter() -> None:
    from eval.run_eval import flashnovel_event_complete

    def chapter_events(chapter: int, *, include_commit: bool = True) -> list[dict]:
        events = [
            {
                "type": "node.completed",
                "payload": {
                    "chapter": chapter,
                    "message": f"context loaded for chapter {chapter}",
                },
            },
            {"type": "chapter.planned", "payload": {"chapter": chapter}},
            {"type": "chapter.drafted", "payload": {"chapter": chapter}},
            {
                "type": "node.completed",
                "payload": {
                    "chapter": chapter,
                    "message": f"candidate memory extracted for chapter {chapter}",
                },
            },
            {
                "type": "node.completed",
                "payload": {
                    "chapter": chapter,
                    "message": f"consistency checked for chapter {chapter}",
                },
            },
            {"type": "chapter.reviewed", "payload": {"chapter": chapter}},
        ]
        if include_commit:
            events.append(
                {"type": "chapter.committed", "payload": {"chapter": chapter}}
            )
        return events

    events = chapter_events(6) + chapter_events(7, include_commit=False)

    assert flashnovel_event_complete(events, expected_chapters=(6, 7)) is False


def test_memory_evidence_writes_before_after_and_semantic_delta(tmp_path) -> None:
    from eval.run_eval import _save_memory_evidence

    case_dir = tmp_path / "case"
    case_dir.mkdir()
    before = {
        "episodic": {
            "recent_summaries": [
                {"id": "seed", "chapter": 5, "summary": "seed summary"}
            ]
        }
    }
    after = {
        "episodic": {
            "recent_summaries": [
                {"id": "new-id", "chapter": 5, "summary": "seed summary"}
            ]
        }
    }

    evidence = _save_memory_evidence(case_dir, before, after)

    assert Path(evidence["memory_before_path"]).is_file()
    assert Path(evidence["memory_after_path"]).is_file()
    assert Path(evidence["memory_delta_path"]).is_file()
    assert evidence["memory_written"] is False
    assert all(not item["written"] for item in evidence["memory_deltas"])


def test_eval_client_records_success_missing_usage_and_failure() -> None:
    from app.llm.client import ChatCompletion, ChatUsage
    from eval.run_eval import EvalClient

    class InnerClient:
        def __init__(self) -> None:
            self.config = type("Config", (), {"model": "configured-model"})()
            self.responses = [
                ChatCompletion(
                    content="with usage",
                    raw={},
                    model="response-model",
                    usage=ChatUsage(
                        prompt_tokens=10,
                        completion_tokens=4,
                        total_tokens=14,
                    ),
                ),
                ChatCompletion(content="without usage", raw={}, model=None),
                RuntimeError("judge failed"),
            ]

        def complete_sync(self, messages, **kwargs):
            _ = messages, kwargs
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    client = EvalClient(InnerClient())
    client.complete_text(
        "baseline",
        stage="baseline_generation",
        case_id="case-1",
        system="naive_recent_text",
    )
    client.complete_text(
        "judge",
        stage="judge.continuity",
        case_id="case-1",
        system="naive_recent_text",
        response_format="json_object",
    )
    with pytest.raises(RuntimeError, match="judge failed"):
        client.complete_text(
            "judge",
            stage="judge.coverage",
            case_id="case-1",
            system="naive_recent_text",
            response_format="json_object",
        )

    assert client.calls == 3
    assert client.attempted_count == 3
    assert len(client.records) == 3
    assert client.records[0].stage == "baseline_generation"
    assert client.records[0].model == "response-model"
    assert client.records[0].usage_status == "complete"
    assert client.records[0].total_tokens == 14
    assert client.records[0].latency_ms >= 0
    assert client.records[1].stage == "judge.continuity"
    assert client.records[1].model == "configured-model"
    assert client.records[1].usage_status == "unavailable"
    assert client.records[1].total_tokens is None
    assert client.records[2].status == "failed"
    assert client.records[2].error_type == "RuntimeError"
    assert client.records[2].error == "judge failed"


def test_run_judges_records_distinct_judge_stages(tmp_path) -> None:
    from app.llm.client import ChatCompletion
    from eval.metrics import load_dataset
    from eval.run_eval import EvalClient, _run_judges

    class InnerClient:
        def __init__(self) -> None:
            self.config = type("Config", (), {"model": "judge-model"})()

        def complete_sync(self, messages, **kwargs):
            _ = messages, kwargs
            return ChatCompletion(
                content='{"coverage_score": 1, "continuity_score": 1}',
                raw={},
                model="judge-model",
            )

    case = load_dataset(
        PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl"
    )[0]
    chapter_path = tmp_path / "chapter.md"
    chapter_path.write_text("test chapter", encoding="utf-8")
    client = EvalClient(InnerClient())

    _run_judges(
        case,
        {
            "case_id": case["id"],
            "system": "naive_recent_text",
            "chapter_path": str(chapter_path),
        },
        tmp_path,
        client,
    )

    assert [record.stage for record in client.records] == [
        "judge.continuity",
        "judge.coverage",
    ]


def test_full_context_usage_reads_actual_prompt_artifact_metadata(tmp_path) -> None:
    from app.memory.store import FlashNovelStore
    from eval.run_eval import _context_usages_from_prompt_artifacts

    store = FlashNovelStore(tmp_path / "store.sqlite3", tmp_path / "artifacts")
    store.initialize()
    story = store.create_story("Context", "Actual context", story_id="story_context")
    workspace = store.create_workspace(story.id, workspace_id=story.id)
    run = store.create_run(
        story_id=story.id,
        workspace_id=workspace.id,
        run_id="run_context",
    )
    store.save_artifact(
        story_id=story.id,
        run_id=run.id,
        chapter=6,
        kind="prompt",
        extension="json",
        content=json.dumps(
            {
                "tool": "plan_chapter",
                "context": {
                    "story": {"title": "Context"},
                    "_context_budget": {
                        "token_budget": 8000,
                        "estimated_tokens": 321,
                    },
                },
            }
        ),
    )

    usages = _context_usages_from_prompt_artifacts(
        store,
        story_id=story.id,
        run_id=run.id,
        start_chapter=6,
        target_chapters=1,
        fallback_budget=9999,
    )

    assert len(usages) == 1
    assert usages[0].chapter == 6
    assert usages[0].budget == 8000
    assert usages[0].estimated_tokens == 321
    assert usages[0].source == "context_budget_metadata"
    assert usages[0].passed is True


def test_full_context_usage_estimates_actual_context_and_marks_missing_artifact(tmp_path) -> None:
    from app.memory.store import FlashNovelStore
    from eval.run_eval import _context_usages_from_prompt_artifacts

    store = FlashNovelStore(tmp_path / "store.sqlite3", tmp_path / "artifacts")
    store.initialize()
    story = store.create_story("Context", "Actual context", story_id="story_context_fallback")
    workspace = store.create_workspace(story.id, workspace_id=story.id)
    run = store.create_run(
        story_id=story.id,
        workspace_id=workspace.id,
        run_id="run_context_fallback",
    )
    store.save_artifact(
        story_id=story.id,
        run_id=run.id,
        chapter=6,
        kind="prompt",
        extension="json",
        content=json.dumps(
            {
                "tool": "plan_chapter",
                "context": {"characters": [{"name": "小黑"}]},
            },
            ensure_ascii=False,
        ),
    )

    usages = _context_usages_from_prompt_artifacts(
        store,
        story_id=story.id,
        run_id=run.id,
        start_chapter=6,
        target_chapters=2,
        fallback_budget=1000,
    )

    assert usages[0].source == "actual_context_estimate"
    assert usages[0].estimated_tokens > 0
    assert usages[0].passed is True
    assert usages[1].chapter == 7
    assert usages[1].source == "unavailable"
    assert usages[1].passed is None
    assert "prompt artifact" in usages[1].reason


def test_full_workflow_call_events_become_eval_call_records() -> None:
    from eval.run_eval import _llm_call_records_from_events

    records = _llm_call_records_from_events(
        [
            {
                "type": "llm.call",
                "payload": {
                    "call_id": "call-ok",
                    "tool": "plan_chapter",
                    "mode": "sync",
                    "model": "model-a",
                    "status": "completed",
                    "latency_ms": 12.5,
                    "usage_status": "complete",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            },
            {
                "type": "llm.call",
                "payload": {
                    "call_id": "call-failed",
                    "tool": "draft_chapter",
                    "mode": "stream",
                    "model": "model-b",
                    "status": "failed",
                    "latency_ms": 8,
                    "usage_status": "unavailable",
                    "error_type": "RuntimeError",
                    "error": "stream failed",
                },
            },
        ],
        case_id="case-1",
        system="flashnovel_full",
        run_id="run-1",
    )

    assert len(records) == 2
    assert records[0].stage == "plan_chapter"
    assert records[0].total_tokens == 15
    assert records[1].status == "failed"
    assert records[1].error == "stream failed"


def test_runner_uses_append_only_directory_and_emits_schema_v2(tmp_path, monkeypatch) -> None:
    import eval.run_eval as runner

    class FixedDatetime:
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime

            return datetime(2026, 6, 7, tzinfo=tz)

    monkeypatch.setattr(runner, "datetime", FixedDatetime)
    output_dir = tmp_path / "results"
    historical = output_dir / "20260607T000000Z"
    historical.mkdir(parents=True)
    sentinel = historical / "sentinel.txt"
    sentinel.write_text("historical result", encoding="utf-8")

    summary = runner.run_eval(
        runner.EvalConfig(
            dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
            output_dir=output_dir,
            systems=("naive_recent_text",),
            limit=1,
            live=False,
            judge=False,
        )
    )

    assert sentinel.read_text(encoding="utf-8") == "historical result"
    assert Path(summary["run_dir"]).name == "20260607T000000Z-2"
    assert summary["summary_schema_version"] == "2.0"
    assert summary["execution_scope"]["coverage_status"] == "partial"


def test_dry_run_never_instantiates_client_factory_or_requires_api_key(
    tmp_path,
    monkeypatch,
) -> None:
    from eval.run_eval import EvalConfig, run_eval

    for key in ("FLASHNOVEL_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(key, "")

    def forbidden_factory():
        raise AssertionError("dry-run must not instantiate an LLM client")

    summary = run_eval(
        EvalConfig(
            dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
            output_dir=tmp_path / "results",
            systems=(
                "naive_recent_text",
                "structured_memory_only",
                "flashnovel_full",
            ),
            limit=1,
            live=False,
            judge=True,
        ),
        client_factory=forbidden_factory,
    )

    assert summary["mode"] == "dry-run"
    assert summary["llm_calls"]["attempted_count"] == 0
    assert summary["llm_calls"]["observed_count"] == 0
    assert summary["execution_scope"]["coverage_status"] == "partial"


def test_judge_failure_does_not_reclassify_successful_generation_as_failed(
    tmp_path,
    monkeypatch,
) -> None:
    from app.llm.client import ChatCompletion
    from eval.run_eval import EvalClient, EvalConfig, run_eval

    monkeypatch.setenv("FLASHNOVEL_API_KEY", "test-only-placeholder")

    class InnerClient:
        def __init__(self) -> None:
            self.config = type("Config", (), {"model": "fake-model"})()
            self.call_index = 0

        def complete_sync(self, messages, **kwargs):
            _ = messages, kwargs
            self.call_index += 1
            if self.call_index == 1:
                return ChatCompletion(
                    content="# Chapter 6\n\nGenerated chapter.",
                    raw={},
                    model="fake-model",
                )
            if self.call_index == 2:
                raise RuntimeError("continuity judge unavailable")
            return ChatCompletion(
                content='{"coverage_score": 0.8}',
                raw={},
                model="fake-model",
            )

    summary = run_eval(
        EvalConfig(
            dataset=PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl",
            output_dir=tmp_path / "results",
            systems=("naive_recent_text",),
            limit=1,
            live=True,
            judge=True,
        ),
        client_factory=lambda: EvalClient(InnerClient()),
    )

    result = summary["results"][0]
    assert result["status"] == "completed"
    assert result["chapter_complete"] is True
    assert result["judges"]["continuity"]["status"] == "failed"
    assert "continuity judge unavailable" in result["judges"]["continuity"]["error"]
    assert result["judges"]["coverage"]["status"] == "completed"
    assert (
        summary["by_system"]["naive_recent_text"]["soft_metrics"]["continuity_score"]["status"]
        == "unavailable"
    )


def test_full_workflow_failure_preserves_runtime_call_records(
    tmp_path,
    monkeypatch,
) -> None:
    from eval.run_eval import EvalConfig, _run_flashnovel_full

    events = [
        {
            "seq": 1,
            "type": "llm.call",
            "payload": {
                "call_id": "failed-call",
                "tool": "plan_chapter",
                "mode": "sync",
                "model": "fake-model",
                "status": "failed",
                "latency_ms": 5,
                "usage_status": "unavailable",
                "error_type": "RuntimeError",
                "error": "provider failed",
            },
        },
        {
            "seq": 2,
            "type": "run.failed",
            "payload": {"message": "run failed", "error": "provider failed"},
        },
    ]

    class FakeRegistry:
        def claim_next(self):
            return type("Task", (), {"run_id": "run-failed"})()

        def finish(self, task):
            _ = task

    class FakeStore:
        def list_artifacts(self, **kwargs):
            _ = kwargs
            return []

    class FakeService:
        def __init__(self, data_dir):
            _ = data_dir
            self.registry = FakeRegistry()
            self.store = FakeStore()

        def create_story(self, request):
            _ = request
            return {"story_id": "story-failed"}

        def get_memory(self, story_id):
            _ = story_id
            return {"episodic": {"recent_summaries": []}}

        def create_run(self, request):
            _ = request
            return {"run_id": "run-failed"}

        def execute_task(self, task):
            _ = task
            raise RuntimeError("provider failed")

        def get_run(self, run_id):
            _ = run_id
            return {"status": "failed"}

        def get_run_events(self, run_id, *, after_seq, limit):
            _ = run_id, limit
            return events if after_seq == 0 else []

        def get_artifacts(self, story_id):
            _ = story_id
            return []

    import app.runtime.service as service_module

    monkeypatch.setattr(service_module, "FlashNovelService", FakeService)
    case = {
        "id": "case-failed",
        "story": {"title": "Failure", "premise": "test", "genre": "test"},
        "seed_memory": {},
        "recent_context": {},
        "run": {
            "prompt": "continue",
            "start_chapter": 1,
            "max_chapters": 1,
            "context_budget": 1000,
        },
        "oracle": {"must_cover": ["x"], "must_not": ["y"]},
    }

    result = _run_flashnovel_full(
        case,
        EvalConfig(output_dir=tmp_path, data_dir=tmp_path / "data"),
        tmp_path / "run",
        None,
    )

    assert result["status"] == "failed"
    assert result["error"] == "RuntimeError: provider failed"
    assert result["llm_attempted_count"] == 1
    assert result["llm_calls"][0]["status"] == "failed"
    assert result["llm_calls"][0]["error"] == "provider failed"


def test_full_failure_before_snapshots_marks_memory_write_unavailable(tmp_path) -> None:
    from eval.run_eval import _failed_result

    case = {
        "id": "case-no-snapshot",
        "run": {"max_chapters": 1, "context_budget": 1000},
    }

    result = _failed_result(
        case,
        "flashnovel_full",
        tmp_path,
        RuntimeError("failed before store setup"),
        mode="live",
    )

    assert result["memory_written"] is None
