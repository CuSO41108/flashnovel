from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.env import load_env
from app.llm.client import ChatMessage, OpenAICompatibleClient
from eval.metrics import (
    aggregate_by_system,
    aggregate_by_tag,
    build_dataset_scope,
    build_execution_scope,
    calculate_memory_deltas,
    load_dataset,
    memory_was_written,
    select_cases,
    unavailable_metric_registry,
    validate_systems,
)
from eval.models import ContextUsage, LLMCallRecord, to_jsonable
from eval.reporting import render_report


DEFAULT_DATASET = PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "results"
SYSTEMS = ("naive_recent_text", "structured_memory_only", "flashnovel_full")
BASELINE_PROMPTS = {
    "naive_recent_text": PROJECT_ROOT / "eval" / "baselines" / "recent_text_prompt.md",
    "structured_memory_only": PROJECT_ROOT / "eval" / "baselines" / "structured_memory_prompt.md",
}
JUDGE_PROMPTS = {
    "continuity": PROJECT_ROOT / "eval" / "rubrics" / "continuity_judge_prompt.md",
    "coverage": PROJECT_ROOT / "eval" / "rubrics" / "coverage_judge_prompt.md",
}
@dataclass(frozen=True)
class EvalConfig:
    dataset: Path = DEFAULT_DATASET
    output_dir: Path = DEFAULT_OUTPUT_DIR
    systems: Sequence[str] = SYSTEMS
    limit: int | None = None
    case_ids: Sequence[str] = ()
    live: bool = False
    judge: bool = True
    data_dir: Path | None = None


class EvalClient:
    def __init__(self, client: OpenAICompatibleClient) -> None:
        self.client = client
        self.calls = 0
        self.attempted_count = 0
        self.records: list[LLMCallRecord] = []

    @classmethod
    def from_env(cls) -> "EvalClient":
        _configure_deepseek_env_fallback()
        return cls(OpenAICompatibleClient.from_env())

    def complete_text(
        self,
        prompt: str,
        *,
        stage: str = "eval.complete",
        case_id: str | None = None,
        system: str | None = None,
        mode: str = "sync",
        run_id: str | None = None,
        temperature: float = 0.7,
        response_format: str | Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        self.calls += 1
        self.attempted_count += 1
        call_id = str(uuid4())
        started = perf_counter()
        try:
            completion = self.client.complete_sync(
                [ChatMessage(role="user", content=prompt)],
                temperature=temperature,
                response_format=response_format,
            )
        except Exception as exc:
            self.records.append(
                LLMCallRecord(
                    call_id=call_id,
                    case_id=case_id,
                    system=system,
                    run_id=run_id,
                    stage=stage,
                    mode=mode,
                    model=getattr(getattr(self.client, "config", None), "model", None),
                    status="failed",
                    latency_ms=round((perf_counter() - started) * 1000, 3),
                    usage_status="unavailable",
                    error_type=type(exc).__name__,
                    error=str(exc)[:500],
                )
            )
            raise
        usage = {}
        if completion.usage is not None:
            usage = {
                key: value
                for key, value in {
                    "prompt_tokens": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "total_tokens": completion.usage.total_tokens,
                }.items()
                if value is not None
            }
        expected_usage = {"prompt_tokens", "completion_tokens", "total_tokens"}
        if not usage:
            usage_status = "unavailable"
        elif expected_usage.issubset(usage):
            usage_status = "complete"
        else:
            usage_status = "incomplete"
        model = completion.model or getattr(
            getattr(self.client, "config", None),
            "model",
            None,
        )
        self.records.append(
            LLMCallRecord(
                call_id=call_id,
                case_id=case_id,
                system=system,
                run_id=run_id,
                stage=stage,
                mode=mode,
                model=model,
                status="completed",
                latency_ms=round((perf_counter() - started) * 1000, 3),
                usage_status=usage_status,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
        )
        return completion.content, {
            "model": model,
            "finish_reason": completion.finish_reason,
            "usage": usage,
            "call_id": call_id,
        }


def run_eval(config: EvalConfig, client_factory: Callable[[], EvalClient] | None = None) -> dict[str, Any]:
    config = _normalize_config(config)
    load_env()
    if config.live:
        _require_live_credentials()
    all_cases = load_dataset(config.dataset)
    cases = select_cases(all_cases, case_ids=config.case_ids, limit=config.limit)
    run_dir = _new_run_dir(config.output_dir)
    results_dir = run_dir / "runs"
    judges_dir = run_dir / "judges"
    results_dir.mkdir(parents=True, exist_ok=True)
    judges_dir.mkdir(parents=True, exist_ok=True)
    client = (client_factory or EvalClient.from_env)() if config.live else None

    results: list[dict[str, Any]] = []
    for case in cases:
        for system in config.systems:
            call_start = len(getattr(client, "records", ())) if client is not None else 0
            attempted_start = (
                int(getattr(client, "attempted_count", getattr(client, "calls", 0)))
                if client is not None
                else 0
            )
            try:
                if system == "flashnovel_full":
                    result = _run_flashnovel_full(case, config, run_dir, client) if config.live else _dry_run(case, system, run_dir)
                elif system in BASELINE_PROMPTS:
                    result = _run_baseline(case, system, run_dir, client) if config.live else _dry_run(case, system, run_dir)
                else:
                    raise ValueError(f"unknown eval system: {system}")
                if (
                    config.live
                    and config.judge
                    and result.get("artifact_exists")
                    and str(result.get("status"))
                    in {"completed", "awaiting_confirmation"}
                ):
                    result["judges"] = _run_judges(case, result, judges_dir, client)
            except Exception as exc:
                result = _failed_result(
                    case,
                    system,
                    run_dir,
                    exc,
                    mode="live" if config.live else "dry-run",
                )
            eval_call_records = list(getattr(client, "records", ()))[call_start:] if client is not None else []
            attempted_end = (
                int(getattr(client, "attempted_count", getattr(client, "calls", 0)))
                if client is not None
                else attempted_start
            )
            existing_calls = list(result.get("llm_calls") or [])
            result["llm_calls"] = existing_calls + to_jsonable(eval_call_records)
            result["llm_attempted_count"] = int(
                result.get("llm_attempted_count") or 0
            ) + max(0, attempted_end - attempted_start)
            results.append(result)

    live_calls = sum(int(result.get("llm_attempted_count") or 0) for result in results)
    summary = _build_summary(
        config=config,
        run_dir=run_dir,
        all_cases=all_cases,
        cases=cases,
        results=results,
        live_llm_calls=live_calls,
    )
    summary_path = run_dir / "summary.json"
    report_path = run_dir / "eval_report.md"
    summary["summary_path"] = str(summary_path)
    summary["report_path"] = str(report_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    systems = _parse_systems(args.systems)
    config = EvalConfig(
        dataset=Path(args.dataset),
        output_dir=Path(args.output_dir),
        systems=systems,
        limit=args.limit,
        case_ids=tuple(args.case_id or ()),
        live=args.live,
        judge=not args.no_judge,
        data_dir=Path(args.data_dir) if args.data_dir else None,
    )
    summary = run_eval(config)
    print(json.dumps(_console_summary(summary), ensure_ascii=False, indent=2))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FlashNovel eval v1.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="JSONL dataset path.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for eval results.")
    parser.add_argument(
        "--systems",
        default=",".join(SYSTEMS),
        help="Comma-separated systems: naive_recent_text,structured_memory_only,flashnovel_full",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of dataset cases.")
    parser.add_argument("--case-id", action="append", help="Run only matching case id. Can be repeated.")
    parser.add_argument("--live", action="store_true", help="Call the configured OpenAI-compatible LLM.")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge calls in live mode.")
    parser.add_argument("--data-dir", default="", help="Data directory for flashnovel_full live runs.")
    return parser


def _normalize_config(config: EvalConfig) -> EvalConfig:
    systems = validate_systems(tuple(config.systems), declared_systems=SYSTEMS)
    return EvalConfig(
        dataset=Path(config.dataset),
        output_dir=Path(config.output_dir),
        systems=systems,
        limit=config.limit,
        case_ids=tuple(config.case_ids),
        live=bool(config.live),
        judge=bool(config.judge),
        data_dir=Path(config.data_dir) if config.data_dir else None,
    )


def _new_run_dir(output_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / stamp
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = output_dir / f"{stamp}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _run_baseline(case: Mapping[str, Any], system: str, run_dir: Path, client: EvalClient | None) -> dict[str, Any]:
    if client is None:
        raise RuntimeError("live baseline run requires an EvalClient")
    prompt = _render_case_prompt(BASELINE_PROMPTS[system], case)
    case_dir = _case_system_dir(run_dir, str(case["id"]), system)
    prompt_path = case_dir / "prompt.md"
    chapter_path = case_dir / "chapter.md"
    meta_path = case_dir / "completion.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    chapter_text, completion_meta = client.complete_text(
        prompt,
        stage="baseline_generation",
        case_id=str(case["id"]),
        system=system,
        temperature=0.7,
    )
    chapter_path.write_text(chapter_text, encoding="utf-8")
    meta_path.write_text(json.dumps(completion_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    target_chapters = _target_chapter_count(case)
    generated_chapters = _count_generated_chapters(chapter_text)
    return {
        "case_id": case["id"],
        "system": system,
        "mode": "live",
        "status": "completed",
        "prompt_path": str(prompt_path),
        "chapter_path": str(chapter_path),
        "completion_path": str(meta_path),
        "estimated_tokens": _estimate_tokens(prompt),
        "context_budget": int((case.get("run") or {}).get("context_budget") or 0),
        "context_usages": [
            {
                "chapter": int((case.get("run") or {}).get("start_chapter") or 1),
                "budget": int((case.get("run") or {}).get("context_budget") or 0),
                "estimated_tokens": _estimate_tokens(prompt),
                "source": "actual_context_estimate",
                "passed": (
                    int((case.get("run") or {}).get("context_budget") or 0) <= 0
                    or _estimate_tokens(prompt)
                    <= int((case.get("run") or {}).get("context_budget") or 0)
                ),
                "reason": None,
            }
        ],
        "target_chapter_count": target_chapters,
        "generated_chapter_count": generated_chapters,
        "chapter_complete": generated_chapters >= target_chapters,
        "artifact_exists": chapter_path.is_file(),
        "event_complete": None,
        "checkpoint_created": None,
        "memory_written": None,
        "usage": completion_meta.get("usage") or {},
        "model": completion_meta.get("model"),
    }


def _dry_run(case: Mapping[str, Any], system: str, run_dir: Path) -> dict[str, Any]:
    prompt_path_template = BASELINE_PROMPTS.get(system)
    prompt = (
        _render_case_prompt(prompt_path_template, case)
        if prompt_path_template is not None
        else _render_flashnovel_dry_prompt(case)
    )
    chapter = _dry_chapter(case, system)
    case_dir = _case_system_dir(run_dir, str(case["id"]), system)
    prompt_path = case_dir / "prompt.md"
    chapter_path = case_dir / "chapter.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    chapter_path.write_text(chapter, encoding="utf-8")
    target_chapters = _target_chapter_count(case)
    return {
        "case_id": case["id"],
        "system": system,
        "mode": "dry-run",
        "status": "dry_run",
        "prompt_path": str(prompt_path),
        "chapter_path": str(chapter_path),
        "estimated_tokens": _estimate_tokens(prompt),
        "context_budget": int((case.get("run") or {}).get("context_budget") or 0),
        "context_usages": [],
        "target_chapter_count": target_chapters,
        "generated_chapter_count": 0,
        "chapter_complete": False,
        "artifact_exists": chapter_path.is_file(),
        "event_complete": None,
        "checkpoint_created": None,
        "memory_written": None,
        "usage": {},
    }


def _failed_result(
    case: Mapping[str, Any],
    system: str,
    run_dir: Path,
    exc: Exception,
    *,
    mode: str,
) -> dict[str, Any]:
    case_dir = _case_system_dir(run_dir, str(case["id"]), system)
    error_path = case_dir / "error.json"
    payload = {
        "case_id": case["id"],
        "system": system,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
    error_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "case_id": case["id"],
        "system": system,
        "mode": mode,
        "status": "failed",
        "error": f"{type(exc).__name__}: {exc}",
        "error_path": str(error_path),
        "estimated_tokens": 0,
        "context_budget": int((case.get("run") or {}).get("context_budget") or 0),
        "context_usages": [],
        "target_chapter_count": _target_chapter_count(case),
        "generated_chapter_count": 0,
        "chapter_complete": False,
        "artifact_exists": False,
        "event_complete": False,
        "checkpoint_created": False,
        "memory_written": None,
        "usage": {},
    }


def _run_flashnovel_full(
    case: Mapping[str, Any],
    config: EvalConfig,
    run_dir: Path,
    client: EvalClient | None,
) -> dict[str, Any]:
    _ = client
    from app.api.dto import CharacterInput, CreateRunRequest, CreateStoryRequest
    from app.domain import (
        ChapterSummary,
        Character,
        Foreshadow,
        Relationship,
        ReviewIssue,
        StateChange,
        TimelineEvent,
        WorldRule,
    )
    from app.runtime.service import FlashNovelService

    data_root = config.data_dir or (run_dir / "flashnovel_data")
    service = FlashNovelService(data_dir=str(data_root))
    story_data = case["story"]
    seed_memory = case.get("seed_memory") or {}
    story = service.create_story(
        CreateStoryRequest(
            title=str(story_data.get("title") or ""),
            premise=str(story_data.get("premise") or ""),
            genre=str(story_data.get("genre") or ""),
            characters=[
                CharacterInput(
                    name=str(item.get("name") or ""),
                    role=str(item.get("role") or ""),
                    description=str(item.get("state") or ""),
                )
                for item in seed_memory.get("characters", [])
            ],
        )
    )
    story_id = str(story["story_id"])
    workspace_id = story_id
    for item in seed_memory.get("characters", []):
        service.store.save_character(
            Character(
                story_id=story_id,
                workspace_id=workspace_id,
                name=str(item.get("name") or ""),
                role=str(item.get("role") or ""),
                description=str(item.get("state") or ""),
                metadata={"source": "eval.seed"},
            )
        )
    for rule in seed_memory.get("world_rules", []):
        service.store.save_world_rule(
            WorldRule(
                story_id=story_id,
                workspace_id=workspace_id,
                category="eval_seed",
                rule=str(rule),
                metadata={"source": "eval.seed"},
            )
        )
    for sequence, raw in enumerate(seed_memory.get("timeline", []), 1):
        chapter, event = _split_chapter_text(str(raw))
        service.store.save_timeline_event(
            TimelineEvent(
                story_id=story_id,
                workspace_id=workspace_id,
                chapter=chapter or max(1, int((case["run"].get("start_chapter") or 1)) - 1),
                sequence=sequence,
                event=event,
                metadata={"source": "eval.seed"},
            )
        )
    for raw in seed_memory.get("relationships", []):
        source, target, relationship = _parse_relationship(str(raw))
        service.store.save_relationship(
            Relationship(
                story_id=story_id,
                workspace_id=workspace_id,
                source=source,
                target=target,
                relationship=relationship,
                metadata={"source": "eval.seed"},
            )
        )
    for item in seed_memory.get("foreshadows", []):
        service.store.save_foreshadow(
            Foreshadow(
                story_id=story_id,
                workspace_id=workspace_id,
                key=str(item.get("key") or "eval_foreshadow"),
                description=str(item.get("description") or ""),
                status=str(item.get("status") or "open"),
                metadata={"source": "eval.seed"},
            )
        )
    for raw in seed_memory.get("state_changes", []):
        entity, after = _split_colon_text(str(raw))
        service.store.save_state_change(
            StateChange(
                story_id=story_id,
                workspace_id=workspace_id,
                chapter=max(1, int((case["run"].get("start_chapter") or 1)) - 1),
                entity=entity,
                attribute="state",
                after=after,
                metadata={"source": "eval.seed"},
            )
        )
    for raw in seed_memory.get("review_issues", []):
        service.store.save_review_issue(
            ReviewIssue(
                story_id=story_id,
                workspace_id=workspace_id,
                chapter=max(1, int((case["run"].get("start_chapter") or 1)) - 1),
                description=str(raw),
                metadata={"source": "eval.seed"},
            )
        )
    for sequence, summary in enumerate((case.get("recent_context") or {}).get("recent_summaries", []), 1):
        chapter, text = _split_chapter_text(str(summary))
        service.store.save_chapter_summary(
            ChapterSummary(
                story_id=story_id,
                workspace_id=workspace_id,
                chapter=chapter or sequence,
                title=f"第{chapter or sequence}章",
                summary=text,
                metadata={"source": "eval.recent_context"},
            )
        )
    memory_before = service.get_memory(story_id)
    run = service.create_run(
        CreateRunRequest(
            story_id=story_id,
            prompt=str(case["run"].get("prompt") or ""),
            max_chapters=int(case["run"].get("max_chapters") or 1),
            context_budget=int(case["run"].get("context_budget") or 0),
        )
    )
    task = service.registry.claim_next()
    if task is None:
        raise RuntimeError("flashnovel_full live run did not enqueue a task")
    execution_error: Exception | None = None
    try:
        service.execute_task(task)
    except Exception as exc:
        execution_error = exc
    finally:
        service.registry.finish(task)
    run_id = str(run["run_id"])
    final_run = service.get_run(run_id)
    events = _list_all_run_events(service, run_id)
    story_artifacts = service.get_artifacts(story_id)
    chapter_artifacts = [
        item
        for item in story_artifacts
        if item.get("run_id") == run_id and item.get("kind") == "chapter"
    ]
    case_dir = _case_system_dir(run_dir, str(case["id"]), "flashnovel_full")
    prompt_path = case_dir / "prompt.md"
    chapter_path = case_dir / "chapter.md"
    events_path = case_dir / "events.json"
    prompt_path.write_text(_render_flashnovel_dry_prompt(case), encoding="utf-8")
    chapter_texts: list[str] = []
    for artifact in sorted(chapter_artifacts, key=lambda item: int(item.get("chapter") or 0)):
        text = service.store.read_artifact_text(str(artifact["id"]))
        chapter_texts.append(f"# Chapter {artifact.get('chapter')}\n\n{text}")
    chapter_path.write_text("\n\n".join(chapter_texts), encoding="utf-8")
    events_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    memory_after = service.get_memory(story_id)
    memory_evidence = _save_memory_evidence(case_dir, memory_before, memory_after)
    target_chapters = _target_chapter_count(case)
    generated_chapters = len(chapter_artifacts)
    context_usages = _context_usages_from_prompt_artifacts(
        service.store,
        story_id=story_id,
        run_id=run_id,
        start_chapter=int(case["run"].get("start_chapter") or 1),
        target_chapters=target_chapters,
        fallback_budget=int(case["run"].get("context_budget") or 0),
    )
    workflow_call_records = _llm_call_records_from_events(
        events,
        case_id=str(case["id"]),
        system="flashnovel_full",
        run_id=run_id,
    )
    observed_context_tokens = [
        usage.estimated_tokens
        for usage in context_usages
        if usage.estimated_tokens is not None
    ]
    workflow_llm_calls = len(workflow_call_records)
    result = {
        "case_id": case["id"],
        "system": "flashnovel_full",
        "mode": "live",
        "status": (
            "failed"
            if execution_error is not None
            else str(final_run.get("status") or "")
        ),
        "run_id": run_id,
        "story_id": story_id,
        "prompt_path": str(prompt_path),
        "chapter_path": str(chapter_path),
        "events_path": str(events_path),
        "memory_path": memory_evidence["memory_after_path"],
        **memory_evidence,
        "estimated_tokens": sum(observed_context_tokens) if observed_context_tokens else None,
        "context_budget": int(case["run"].get("context_budget") or 0),
        "context_usages": to_jsonable(context_usages),
        "target_chapter_count": target_chapters,
        "generated_chapter_count": generated_chapters,
        "chapter_complete": generated_chapters >= target_chapters,
        "artifact_exists": bool(chapter_artifacts) and chapter_path.is_file(),
        "event_complete": flashnovel_event_complete(
            events,
            expected_chapters=tuple(
                range(
                    int(case["run"].get("start_chapter") or 1),
                    int(case["run"].get("start_chapter") or 1) + target_chapters,
                )
            ),
        ),
        "checkpoint_created": any(item.get("type") == "checkpoint.created" for item in events),
        "usage": _usage_from_events(events),
        "workflow_llm_calls": workflow_llm_calls,
        "llm_attempted_count": workflow_llm_calls,
        "llm_calls": to_jsonable(workflow_call_records),
    }
    if execution_error is not None:
        result["error_type"] = type(execution_error).__name__
        result["error"] = f"{type(execution_error).__name__}: {execution_error}"
    return result


def _run_judges(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    judges_dir: Path,
    client: EvalClient | None,
) -> dict[str, Any]:
    if client is None:
        raise RuntimeError("live judge run requires an EvalClient")
    chapter_text = Path(str(result["chapter_path"])).read_text(encoding="utf-8")
    outputs: dict[str, Any] = {}
    for name, prompt_path in JUDGE_PROMPTS.items():
        prompt = _render_template(
            prompt_path.read_text(encoding="utf-8"),
            _case_template_values(case, chapter_text=chapter_text),
        )
        try:
            content, meta = client.complete_text(
                prompt,
                stage=f"judge.{name}",
                case_id=str(case["id"]),
                system=str(result["system"]),
                run_id=str(result.get("run_id") or "") or None,
                temperature=0.1,
                response_format="json_object",
            )
            parsed = _json_from_text(content)
            judge_path = judges_dir / f"{case['id']}__{result['system']}__{name}.json"
            judge_path.write_text(
                json.dumps({"judge": parsed, "meta": meta}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            outputs[name] = {
                "status": "completed",
                "path": str(judge_path),
                "result": parsed,
                "usage": meta.get("usage") or {},
            }
        except Exception as exc:
            outputs[name] = {
                "status": "failed",
                "result": None,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
    return outputs


def _render_case_prompt(prompt_path: Path, case: Mapping[str, Any]) -> str:
    return _render_template(prompt_path.read_text(encoding="utf-8"), _case_template_values(case))


def _case_template_values(case: Mapping[str, Any], *, chapter_text: str = "") -> dict[str, str]:
    story = case.get("story") or {}
    run = case.get("run") or {}
    oracle = case.get("oracle") or {}
    recent = case.get("recent_context") or {}
    recent_text = "\n".join(str(item) for item in recent.get("recent_summaries", []))
    return {
        "story": _json_text(story),
        "story_title": str(story.get("title") or ""),
        "genre": str(story.get("genre") or ""),
        "premise": str(story.get("premise") or ""),
        "seed_memory": _json_text(case.get("seed_memory") or {}),
        "recent_text_or_summary": recent_text,
        "start_chapter": str(run.get("start_chapter") or ""),
        "max_chapters": str(run.get("max_chapters") or ""),
        "context_budget": str(run.get("context_budget") or ""),
        "prompt": str(run.get("prompt") or ""),
        "must_cover": _json_text(oracle.get("must_cover") or []),
        "must_not": _json_text(oracle.get("must_not") or []),
        "expected_memory_changes": _json_text(oracle.get("expected_memory_changes") or {}),
        "chapter_text": chapter_text,
    }


def _render_template(template: str, values: Mapping[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _render_flashnovel_dry_prompt(case: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# FlashNovel Full Eval Input",
            "",
            "This prompt snapshot documents the structured run input. In `--live` mode,",
            "FlashNovel executes context -> plan -> draft -> extract -> check -> review -> rewrite -> commit.",
            "",
            "Story:",
            _json_text(case.get("story") or {}),
            "",
            "Seed Memory:",
            _json_text(case.get("seed_memory") or {}),
            "",
            "Run:",
            _json_text(case.get("run") or {}),
            "",
            "Oracle:",
            _json_text(case.get("oracle") or {}),
        ]
    )


def _dry_chapter(case: Mapping[str, Any], system: str) -> str:
    oracle = case.get("oracle") or {}
    lines = [
        f"[DRY RUN] {case['id']} / {system}",
        "",
        "This is a local placeholder artifact. It is not model output and must not be used as an eval score.",
        "",
        "Must cover:",
    ]
    lines.extend(f"- {item}" for item in oracle.get("must_cover", []))
    lines.append("")
    lines.append("Must not:")
    lines.extend(f"- {item}" for item in oracle.get("must_not", []))
    return "\n".join(lines)


def _case_system_dir(run_dir: Path, case_id: str, system: str) -> Path:
    path = run_dir / "runs" / _safe_name(case_id) / _safe_name(system)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_summary(
    *,
    config: EvalConfig,
    run_dir: Path,
    all_cases: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    live_llm_calls: int,
) -> dict[str, Any]:
    mode = "live" if config.live else "dry-run"
    dataset_scope = build_dataset_scope(config.dataset, all_cases)
    execution_scope = build_execution_scope(
        dataset_scope,
        cases,
        config.systems,
        mode=mode,
        judge_enabled=bool(config.live and config.judge),
        results=results,
    )
    by_system = aggregate_by_system(results, systems=config.systems)
    by_tag = aggregate_by_tag(results, cases, systems=config.systems)
    call_records = [
        call
        for result in results
        for call in (result.get("llm_calls") or [])
        if isinstance(call, Mapping)
    ]
    summary = {
        "eval_version": "v1",
        "summary_schema_version": "2.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "run_dir": str(run_dir),
        "dataset_scope": to_jsonable(dataset_scope),
        "execution_scope": to_jsonable(execution_scope),
        "by_system": to_jsonable(by_system),
        "by_tag": to_jsonable(by_tag),
        "llm_calls": {
            "attempted_count": live_llm_calls,
            "observed_count": len(call_records),
            "records": call_records,
        },
        "unavailable_metrics": unavailable_metric_registry(),
        "configuration": {
            "dataset": str(config.dataset),
            "output_dir": str(config.output_dir),
            "systems": list(config.systems),
            "limit": config.limit,
            "case_ids": list(config.case_ids),
            "mode": mode,
            "judge_enabled": bool(config.live and config.judge),
            "data_dir": str(config.data_dir) if config.data_dir else None,
        },
        "results": list(results),
    }
    return summary


def _console_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    execution = summary.get("execution_scope") or {}
    calls = summary.get("llm_calls") or {}
    return {
        "mode": summary.get("mode"),
        "case_count": execution.get("case_count"),
        "systems": execution.get("systems"),
        "coverage_status": execution.get("coverage_status"),
        "live_llm_calls": calls.get("attempted_count"),
        "summary_path": summary.get("summary_path"),
        "report_path": summary.get("report_path"),
    }


def flashnovel_event_complete(
    events: Sequence[Mapping[str, Any]],
    *,
    expected_chapters: Sequence[int] | None = None,
) -> bool:
    required = {"context", "plan", "draft", "extract", "check", "review", "commit"}
    if expected_chapters:
        seen_by_chapter = {int(chapter): set() for chapter in expected_chapters}
        for event in events:
            step = _workflow_event_step(event)
            chapter = _event_chapter(event)
            if step and chapter in seen_by_chapter:
                seen_by_chapter[chapter].add(step)
        return all(required.issubset(seen) for seen in seen_by_chapter.values())

    seen: set[str] = set()
    for event in events:
        step = _workflow_event_step(event)
        if step:
            seen.add(step)
    return required.issubset(seen)


def _workflow_event_step(event: Mapping[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    payload = event.get("payload")
    message = str(payload.get("message") or "") if isinstance(payload, Mapping) else ""
    if event_type == "node.completed" and "context loaded" in message:
        return "context"
    if event_type == "chapter.planned":
        return "plan"
    if event_type == "chapter.drafted":
        return "draft"
    if event_type == "node.completed" and "candidate memory extracted" in message:
        return "extract"
    if event_type == "node.completed" and "consistency checked" in message:
        return "check"
    if event_type == "chapter.reviewed":
        return "review"
    if event_type == "chapter.committed":
        return "commit"
    return None


def _event_chapter(event: Mapping[str, Any]) -> int | None:
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        value = payload.get("chapter")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        message = str(payload.get("message") or "")
        match = re.search(r"chapter\s+(\d+)", message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _save_memory_evidence(
    case_dir: Path,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    memory_before_path = case_dir / "memory_before.json"
    memory_after_path = case_dir / "memory_after.json"
    memory_delta_path = case_dir / "memory_delta.json"
    deltas = calculate_memory_deltas(before, after)
    serialized_deltas = to_jsonable(deltas)
    memory_before_path.write_text(
        json.dumps(before, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    memory_after_path.write_text(
        json.dumps(after, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    memory_delta_path.write_text(
        json.dumps(serialized_deltas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "memory_before_path": str(memory_before_path),
        "memory_after_path": str(memory_after_path),
        "memory_delta_path": str(memory_delta_path),
        "memory_deltas": serialized_deltas,
        "memory_written": memory_was_written(deltas),
    }


def _context_usages_from_prompt_artifacts(
    store: Any,
    *,
    story_id: str,
    run_id: str,
    start_chapter: int,
    target_chapters: int,
    fallback_budget: int,
) -> tuple[ContextUsage, ...]:
    artifacts = store.list_artifacts(
        story_id=story_id,
        run_id=run_id,
        kind="prompt",
    )
    by_chapter = {
        int(_artifact_value(artifact, "chapter") or 0): artifact
        for artifact in artifacts
    }
    usages: list[ContextUsage] = []
    for chapter in range(start_chapter, start_chapter + target_chapters):
        artifact = by_chapter.get(chapter)
        if artifact is None:
            usages.append(
                ContextUsage(
                    chapter=chapter,
                    budget=fallback_budget,
                    estimated_tokens=None,
                    source="unavailable",
                    passed=None,
                    reason="prompt artifact with actual Context Builder input was not captured",
                )
            )
            continue
        try:
            payload = store.read_artifact_json(str(_artifact_value(artifact, "id")))
        except Exception as exc:
            usages.append(
                ContextUsage(
                    chapter=chapter,
                    budget=fallback_budget,
                    estimated_tokens=None,
                    source="unavailable",
                    passed=None,
                    reason=f"prompt artifact could not be read: {type(exc).__name__}",
                )
            )
            continue
        context = payload.get("context") if isinstance(payload, Mapping) else None
        if not isinstance(context, Mapping):
            usages.append(
                ContextUsage(
                    chapter=chapter,
                    budget=fallback_budget,
                    estimated_tokens=None,
                    source="unavailable",
                    passed=None,
                    reason="prompt artifact does not contain a structured context",
                )
            )
            continue
        budget_meta = context.get("_context_budget")
        metadata = budget_meta if isinstance(budget_meta, Mapping) else {}
        budget = _non_negative_int(metadata.get("token_budget"), fallback_budget)
        metadata_estimate = metadata.get("estimated_tokens")
        if (
            isinstance(metadata_estimate, int)
            and not isinstance(metadata_estimate, bool)
            and metadata_estimate >= 0
        ):
            estimated_tokens = metadata_estimate
            source = "context_budget_metadata"
        else:
            estimated_tokens = _estimate_tokens(
                json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
            )
            source = "actual_context_estimate"
        usages.append(
            ContextUsage(
                chapter=chapter,
                budget=budget,
                estimated_tokens=estimated_tokens,
                source=source,
                passed=budget <= 0 or estimated_tokens <= budget,
            )
        )
    return tuple(usages)


def _llm_call_records_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    case_id: str,
    system: str,
    run_id: str,
) -> tuple[LLMCallRecord, ...]:
    records: list[LLMCallRecord] = []
    for event in events:
        if event.get("type") != "llm.call":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        usage = payload.get("usage")
        usage_payload = usage if isinstance(usage, Mapping) else {}
        status = str(payload.get("status") or "failed")
        if status not in {"completed", "failed"}:
            status = "failed"
        usage_status = str(payload.get("usage_status") or "unavailable")
        if usage_status not in {"complete", "incomplete", "unavailable"}:
            usage_status = "unavailable"
        records.append(
            LLMCallRecord(
                call_id=str(payload.get("call_id") or uuid4()),
                case_id=case_id,
                system=system,
                run_id=run_id,
                stage=str(payload.get("tool") or "unknown"),
                mode=str(payload.get("mode") or "unknown"),
                model=str(payload.get("model")) if payload.get("model") else None,
                status=status,
                latency_ms=max(0.0, float(payload.get("latency_ms") or 0)),
                usage_status=usage_status,
                prompt_tokens=_optional_int(usage_payload.get("prompt_tokens")),
                completion_tokens=_optional_int(usage_payload.get("completion_tokens")),
                total_tokens=_optional_int(usage_payload.get("total_tokens")),
                error_type=(
                    str(payload.get("error_type"))
                    if payload.get("error_type")
                    else None
                ),
                error=str(payload.get("error")) if payload.get("error") else None,
            )
        )
    return tuple(records)


def _artifact_value(artifact: Any, field: str) -> Any:
    if isinstance(artifact, Mapping):
        return artifact.get(field)
    return getattr(artifact, field, None)


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return default
    return converted if converted >= 0 else default


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_all_run_events(service: Any, run_id: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    after_seq = 0
    while True:
        batch = service.get_run_events(run_id, after_seq=after_seq, limit=1000)
        if not batch:
            break
        events.extend(batch)
        next_seq = max(int(item.get("seq") or 0) for item in batch)
        if next_seq <= after_seq:
            break
        after_seq = next_seq
    return events


def _require_live_credentials() -> None:
    key = os.getenv("FLASHNOVEL_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "--live requires an API key in FLASHNOVEL_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY"
        )


def _configure_deepseek_env_fallback() -> None:
    if os.getenv("FLASHNOVEL_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        return
    os.environ["FLASHNOVEL_API_KEY"] = deepseek_key
    os.environ.setdefault("FLASHNOVEL_BASE_URL", "https://api.deepseek.com")
    os.environ.setdefault("FLASHNOVEL_MODEL", "deepseek-chat")


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
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {"raw": text}
        payload = json.loads(raw[start : end + 1])
    return payload if isinstance(payload, dict) else {"items": payload}


def _parse_systems(value: str) -> tuple[str, ...]:
    if value.strip().lower() in {"all", "*"}:
        return SYSTEMS
    systems = tuple(item.strip() for item in value.split(",") if item.strip())
    unknown = [system for system in systems if system not in SYSTEMS]
    if unknown:
        raise ValueError(f"unknown eval systems: {', '.join(unknown)}")
    return systems


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def _target_chapter_count(case: Mapping[str, Any]) -> int:
    return int((case.get("run") or {}).get("max_chapters") or 1)


def _count_generated_chapters(text: str) -> int:
    content = (text or "").strip()
    if not content:
        return 0
    headings = re.findall(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:chapter\s+\d+|第[零一二三四五六七八九十百0-9]+章)(?:\s|[:：]|$)",
        content,
    )
    return len(headings) if headings else 1


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return safe or "item"


def _split_chapter_text(value: str) -> tuple[int | None, str]:
    match = re.match(r"第(\d+)章[：:]\s*(.*)$", value)
    if not match:
        return None, value
    return int(match.group(1)), match.group(2).strip()


def _split_colon_text(value: str) -> tuple[str, str]:
    if "：" in value:
        left, right = value.split("：", 1)
    elif ":" in value:
        left, right = value.split(":", 1)
    else:
        return value, value
    return left.strip(), right.strip()


def _parse_relationship(value: str) -> tuple[str, str, str]:
    actors, relation = _split_colon_text(value)
    if "-" in actors:
        source, target = actors.split("-", 1)
        return source.strip(), target.strip(), relation
    return actors, "", relation


def _usage_from_events(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for event in events:
        if event.get("type") != "llm.usage":
            continue
        usage = ((event.get("payload") or {}).get("usage") or {})
        for key in totals:
            try:
                totals[key] += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return {key: value for key, value in totals.items() if value}


if __name__ == "__main__":
    raise SystemExit(main())
