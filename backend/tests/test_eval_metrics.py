from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_eval_models_serialize_recursively() -> None:
    from eval.models import (
        ContextUsage,
        DatasetScope,
        ExecutionScope,
        LLMCallRecord,
        MemoryDelta,
        MetricResult,
        to_jsonable,
    )

    payload = to_jsonable(
        {
            "dataset": DatasetScope(
                dataset_path="eval/datasets/flashnovel_eval_v1.jsonl",
                case_ids=("case-1",),
                case_count=1,
                target_chapters=5,
                tag_counts={"continuity": 1},
            ),
            "execution": ExecutionScope(
                case_ids=("case-1",),
                case_count=1,
                target_chapters=5,
                systems=("flashnovel_full",),
                expected_result_count=1,
                mode="live",
                judge_enabled=True,
                coverage_status="partial",
                coverage_reasons=("missing systems: naive_recent_text, structured_memory_only",),
            ),
            "metric": MetricResult(
                name="run_success_rate",
                status="complete",
                value=1.0,
                numerator=1,
                denominator=1,
                observed_count=1,
                excluded_count=0,
                source="run status",
                applicability="live results",
            ),
            "memory": MemoryDelta(
                category="summaries",
                before_count=1,
                after_count=2,
                added_count=1,
                changed_count=0,
                written=True,
            ),
            "context": ContextUsage(
                chapter=6,
                budget=8000,
                estimated_tokens=1200,
                source="context_budget_metadata",
                passed=True,
            ),
            "call": LLMCallRecord(
                call_id="call-1",
                case_id="case-1",
                system="flashnovel_full",
                run_id="run-1",
                stage="plan_chapter",
                mode="sync",
                model="test-model",
                status="completed",
                latency_ms=12.5,
                usage_status="complete",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        }
    )

    assert payload["dataset"]["case_ids"] == ["case-1"]
    assert payload["execution"]["coverage_status"] == "partial"
    assert payload["metric"]["limitations"] == []
    assert payload["memory"]["written"] is True
    assert payload["context"]["estimated_tokens"] == 1200
    assert payload["call"]["total_tokens"] == 15
    assert payload["call"]["error"] is None


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: __import__("eval.models", fromlist=["ExecutionScope"]).ExecutionScope(
                case_ids=(),
                case_count=0,
                target_chapters=0,
                systems=(),
                expected_result_count=0,
                mode="preview",
                judge_enabled=False,
                coverage_status="partial",
            ),
            "mode",
        ),
        (
            lambda: __import__("eval.models", fromlist=["MetricResult"]).MetricResult(
                name="metric",
                status="unknown",
                value=None,
                numerator=None,
                denominator=0,
                observed_count=0,
                excluded_count=0,
                source="test",
                applicability="test",
            ),
            "status",
        ),
        (
            lambda: __import__("eval.models", fromlist=["LLMCallRecord"]).LLMCallRecord(
                call_id="call",
                stage="judge",
                mode="sync",
                status="pending",
                latency_ms=0,
                usage_status="unavailable",
            ),
            "status",
        ),
    ],
)
def test_eval_models_reject_invalid_enum_values(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def _write_dataset(path: Path, cases: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    return path


def _case(case_id: str, *, max_chapters=1) -> dict:
    run = {"prompt": "continue", "start_chapter": 1, "context_budget": 1000}
    if max_chapters is not None:
        run["max_chapters"] = max_chapters
    return {
        "id": case_id,
        "difficulty": "medium",
        "tags": ["continuity"],
        "story": {"title": case_id, "premise": "test", "genre": "test"},
        "seed_memory": {},
        "recent_context": {},
        "run": run,
        "oracle": {"must_cover": ["required"], "must_not": ["forbidden"]},
    }


def test_current_dataset_scope_is_20_cases_and_28_target_chapters() -> None:
    from eval.metrics import build_dataset_scope, load_dataset

    dataset = PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl"
    cases = load_dataset(dataset)
    scope = build_dataset_scope(dataset, cases)

    assert scope.case_count == 20
    assert scope.target_chapters == 28
    assert len(scope.case_ids) == 20
    assert scope.tag_counts["continuity"] > 0


def test_dataset_is_fully_validated_before_case_filtering(tmp_path) -> None:
    from eval.metrics import load_dataset, select_cases

    dataset = _write_dataset(
        tmp_path / "cases.jsonl",
        [_case("selected"), _case("invalid", max_chapters=0)],
    )

    with pytest.raises(ValueError, match="max_chapters"):
        select_cases(load_dataset(dataset), case_ids=("selected",))


def test_dataset_rejects_duplicate_case_ids_and_invalid_explicit_chapter_counts(tmp_path) -> None:
    from eval.metrics import load_dataset

    duplicate = _write_dataset(
        tmp_path / "duplicate.jsonl",
        [_case("same"), _case("same")],
    )
    with pytest.raises(ValueError, match="duplicate case id"):
        load_dataset(duplicate)

    for index, value in enumerate((0, -1, 1.5, True, "5"), 1):
        invalid = _write_dataset(
            tmp_path / f"invalid-{index}.jsonl",
            [_case(f"case-{index}", max_chapters=value)],
        )
        with pytest.raises(ValueError, match="max_chapters"):
            load_dataset(invalid)


def test_omitted_max_chapters_normalizes_to_one_and_large_limit_selects_all(tmp_path) -> None:
    from eval.metrics import build_dataset_scope, load_dataset, select_cases

    dataset = _write_dataset(
        tmp_path / "cases.jsonl",
        [_case("one", max_chapters=None), _case("two", max_chapters=5)],
    )
    cases = load_dataset(dataset)
    selected = select_cases(cases, limit=99)
    scope = build_dataset_scope(dataset, selected)

    assert selected[0]["run"]["max_chapters"] == 1
    assert scope.case_count == 2
    assert scope.target_chapters == 6


def test_system_selection_rejects_empty_duplicate_and_unknown_values() -> None:
    from eval.metrics import validate_systems

    with pytest.raises(ValueError, match="at least one"):
        validate_systems(())
    with pytest.raises(ValueError, match="duplicate"):
        validate_systems(("naive_recent_text", "naive_recent_text"))
    with pytest.raises(ValueError, match="unknown"):
        validate_systems(("invented",))


def test_hard_metrics_use_explicit_live_only_denominators() -> None:
    from eval.metrics import aggregate_hard_metrics

    results = [
        {
            "mode": "dry-run",
            "system": "flashnovel_full",
            "status": "dry_run",
            "artifact_exists": True,
            "event_complete": True,
            "checkpoint_created": True,
            "memory_written": True,
            "target_chapter_count": 5,
            "context_usages": [{"passed": True}],
        },
        {
            "mode": "live",
            "system": "naive_recent_text",
            "status": "completed",
            "artifact_exists": True,
            "event_complete": None,
            "checkpoint_created": None,
            "memory_written": None,
            "target_chapter_count": 1,
            "context_budget": 1000,
            "context_usages": [{"passed": True}],
        },
        {
            "mode": "live",
            "system": "flashnovel_full",
            "status": "failed",
            "artifact_exists": True,
            "event_complete": False,
            "checkpoint_created": True,
            "memory_written": False,
            "target_chapter_count": 5,
            "context_budget": 1000,
            "context_usages": [],
        },
    ]

    metrics = aggregate_hard_metrics(results)

    assert metrics["run_success_rate"].numerator == 1
    assert metrics["run_success_rate"].denominator == 2
    assert metrics["run_success_rate"].value == 0.5
    assert metrics["artifact_exists_rate"].denominator == 2
    assert metrics["event_complete_rate"].numerator == 0
    assert metrics["event_complete_rate"].denominator == 1
    assert metrics["checkpoint_rate"].numerator == 1
    assert metrics["checkpoint_rate"].denominator == 1
    assert metrics["token_budget_pass_rate"].denominator == 2
    assert metrics["token_budget_pass_rate"].observed_count == 1
    assert metrics["token_budget_pass_rate"].status == "incomplete"
    assert metrics["memory_write_rate"].numerator == 0
    assert metrics["memory_write_rate"].denominator == 1


def test_zero_denominator_metric_is_unavailable_not_zero() -> None:
    from eval.metrics import aggregate_hard_metrics

    metrics = aggregate_hard_metrics(
        [
            {
                "mode": "dry-run",
                "system": "naive_recent_text",
                "status": "dry_run",
                "artifact_exists": True,
                "target_chapter_count": 1,
            }
        ]
    )

    run_success = metrics["run_success_rate"]
    assert run_success.status == "unavailable"
    assert run_success.value is None
    assert run_success.denominator == 0
    assert run_success.excluded_count == 1
    assert "live" in run_success.reason


def test_missing_real_event_data_is_not_treated_as_complete() -> None:
    from eval.metrics import aggregate_hard_metrics

    metric = aggregate_hard_metrics(
        [
            {
                "mode": "live",
                "system": "flashnovel_full",
                "status": "completed",
                "artifact_exists": True,
                "event_complete": None,
                "target_chapter_count": 1,
            }
        ]
    )["event_complete_rate"]

    assert metric.status == "unavailable"
    assert metric.value is None
    assert metric.denominator == 1
    assert metric.observed_count == 0


def test_missing_memory_snapshots_are_unavailable_not_failed_write() -> None:
    from eval.metrics import aggregate_hard_metrics

    metric = aggregate_hard_metrics(
        [
            {
                "mode": "live",
                "system": "flashnovel_full",
                "status": "failed",
                "artifact_exists": False,
                "event_complete": False,
                "checkpoint_created": None,
                "memory_written": None,
                "target_chapter_count": 1,
                "context_budget": 1000,
                "context_usages": [],
            }
        ]
    )["memory_write_rate"]

    assert metric.status == "unavailable"
    assert metric.value is None
    assert metric.denominator == 1
    assert metric.observed_count == 0


def test_seed_only_memory_with_storage_metadata_changes_is_not_a_write() -> None:
    from eval.metrics import calculate_memory_deltas, memory_was_written

    before = {
        "episodic": {
            "recent_summaries": [
                {
                    "id": "before-id",
                    "chapter": 5,
                    "title": "第五章",
                    "summary": "母亲住院。",
                    "key_events": ["住院"],
                    "created_at": "2026-01-01",
                }
            ]
        },
        "continuity": {
            "relationships": [
                {
                    "id": "rel-before",
                    "source": "小黑",
                    "target": "杰瑞",
                    "relationship": "合作",
                    "updated_at": "2026-01-01",
                }
            ]
        },
    }
    after = {
        "episodic": {
            "recent_summaries": [
                {
                    "id": "after-id",
                    "chapter": 5,
                    "title": "第五章",
                    "summary": "母亲住院。",
                    "key_events": ["住院"],
                    "created_at": "2026-06-07",
                }
            ]
        },
        "continuity": {
            "relationships": [
                {
                    "id": "rel-after",
                    "source": "小黑",
                    "target": "杰瑞",
                    "relationship": "合作",
                    "updated_at": "2026-06-07",
                }
            ]
        },
    }

    deltas = calculate_memory_deltas(before, after)

    assert not memory_was_written(deltas)
    assert all(delta.added_count == 0 for delta in deltas)
    assert all(delta.changed_count == 0 for delta in deltas)


def test_memory_content_update_counts_as_changed_even_when_count_is_unchanged() -> None:
    from eval.metrics import calculate_memory_deltas, memory_was_written

    before = {
        "chapter_summaries": [
            {"chapter": 6, "title": "第六章", "summary": "仍然合作", "key_events": []}
        ]
    }
    after = {
        "chapter_summaries": [
            {"chapter": 6, "title": "第六章", "summary": "互相猜疑", "key_events": []}
        ]
    }

    deltas = {delta.category: delta for delta in calculate_memory_deltas(before, after)}

    assert deltas["summaries"].before_count == 1
    assert deltas["summaries"].after_count == 1
    assert deltas["summaries"].added_count == 0
    assert deltas["summaries"].changed_count == 1
    assert memory_was_written(deltas.values())


def test_new_semantic_memory_record_counts_as_added() -> None:
    from eval.metrics import calculate_memory_deltas

    before = {"continuity": {"foreshadows": []}}
    after = {
        "continuity": {
            "foreshadows": [
                {
                    "id": "generated-id",
                    "key": "trade_cost",
                    "description": "交易会夺走记忆",
                    "status": "open",
                    "setup_chapter": 6,
                    "created_at": "2026-06-07",
                }
            ]
        }
    }

    deltas = {delta.category: delta for delta in calculate_memory_deltas(before, after)}

    assert deltas["foreshadows"].before_count == 0
    assert deltas["foreshadows"].after_count == 1
    assert deltas["foreshadows"].added_count == 1
    assert deltas["foreshadows"].written is True
    assert set(deltas) == {
        "summaries",
        "timeline",
        "relationships",
        "foreshadows",
        "state_changes",
    }


def test_results_aggregate_by_system_with_soft_and_call_coverage() -> None:
    from eval.metrics import aggregate_by_system

    results = [
        {
            "case_id": "case-1",
            "system": "naive_recent_text",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "context_budget": 1000,
            "context_usages": [{"passed": True}],
            "target_chapter_count": 1,
            "judges": {
                "coverage": {"result": {"coverage_score": 0.8}},
                "continuity": {
                    "result": {
                        "continuity_score": 0.9,
                        "contradiction_count": 1,
                    }
                },
            },
            "llm_attempted_count": 1,
            "llm_calls": [
                {
                    "latency_ms": 10,
                    "usage_status": "complete",
                    "total_tokens": 100,
                }
            ],
        },
        {
            "case_id": "case-2",
            "system": "naive_recent_text",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "context_budget": 1000,
            "context_usages": [{"passed": True}],
            "target_chapter_count": 1,
            "judges": {
                "coverage": {"result": {"coverage_score": 1.0}},
                "continuity": {
                    "result": {
                        "continuity_score": 0.7,
                        "contradiction_count": 0,
                    }
                },
            },
            "llm_attempted_count": 1,
            "llm_calls": [
                {
                    "latency_ms": 20,
                    "usage_status": "unavailable",
                    "total_tokens": None,
                }
            ],
        },
        {
            "case_id": "case-1",
            "system": "structured_memory_only",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "context_budget": 1000,
            "context_usages": [{"passed": True}],
            "target_chapter_count": 1,
            "judges": {
                "coverage": {"result": {"coverage_score": 0.6}},
                "continuity": {
                    "result": {
                        "continuity_score": 0.95,
                        "contradiction_count": 0,
                    }
                },
            },
            "llm_attempted_count": 2,
            "llm_calls": [
                {
                    "latency_ms": 12,
                    "usage_status": "complete",
                    "total_tokens": 80,
                }
            ],
        },
    ]

    grouped = aggregate_by_system(
        results,
        systems=("naive_recent_text", "structured_memory_only"),
    )

    naive = grouped["naive_recent_text"]
    assert naive["result_count"] == 2
    assert naive["soft_metrics"]["coverage_score"].value == 0.9
    assert naive["soft_metrics"]["coverage_score"].observed_count == 2
    assert naive["soft_metrics"]["continuity_score"].value == 0.8
    assert naive["soft_metrics"]["contradiction_count"].value == 0.5
    assert naive["hard_metrics"]["run_success_rate"].denominator == 2
    assert naive["llm_metrics"]["call_record_coverage"].value == 1.0
    assert naive["llm_metrics"]["usage_coverage_rate"].value == 0.5
    assert naive["llm_metrics"]["average_latency_ms"].value == 15.0
    assert naive["llm_metrics"]["average_total_tokens"].value == 100.0
    assert naive["llm_metrics"]["average_total_tokens"].status == "incomplete"

    structured = grouped["structured_memory_only"]
    assert structured["llm_metrics"]["call_record_coverage"].numerator == 1
    assert structured["llm_metrics"]["call_record_coverage"].denominator == 2


def test_results_aggregate_by_tag_without_mixing_systems() -> None:
    from eval.metrics import aggregate_by_tag

    cases = [
        {"id": "case-1", "tags": ["continuity", "hard"]},
        {"id": "case-2", "tags": ["coverage"]},
    ]
    results = [
        {
            "case_id": "case-1",
            "system": "naive_recent_text",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "target_chapter_count": 1,
            "judges": {"coverage": {"result": {"coverage_score": 0.8}}},
        },
        {
            "case_id": "case-1",
            "system": "structured_memory_only",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "target_chapter_count": 1,
            "judges": {"coverage": {"result": {"coverage_score": 0.6}}},
        },
        {
            "case_id": "case-2",
            "system": "naive_recent_text",
            "mode": "live",
            "status": "completed",
            "artifact_exists": True,
            "target_chapter_count": 1,
            "judges": {"coverage": {"result": {"coverage_score": 1.0}}},
        },
    ]

    grouped = aggregate_by_tag(
        results,
        cases,
        systems=("naive_recent_text", "structured_memory_only"),
    )

    assert grouped["continuity"]["naive_recent_text"]["result_count"] == 1
    assert (
        grouped["continuity"]["naive_recent_text"]["soft_metrics"]["coverage_score"].value
        == 0.8
    )
    assert (
        grouped["continuity"]["structured_memory_only"]["soft_metrics"]["coverage_score"].value
        == 0.6
    )
    assert grouped["coverage"]["naive_recent_text"]["result_count"] == 1
    assert "structured_memory_only" not in grouped["coverage"]


def _complete_results(cases: list[dict], systems: tuple[str, ...]) -> list[dict]:
    return [
        {
            "case_id": case["id"],
            "system": system,
            "mode": "live",
            "status": "completed",
            "target_chapter_count": case["run"]["max_chapters"],
            "generated_chapter_count": case["run"]["max_chapters"],
            "chapter_complete": True,
        }
        for case in cases
        for system in systems
    ]


def test_coverage_status_reports_dry_run_missing_scope_failures_and_chapter_gaps() -> None:
    from eval.metrics import (
        DEFAULT_SYSTEMS,
        build_dataset_scope,
        build_execution_scope,
        load_dataset,
    )

    dataset = PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl"
    cases = load_dataset(dataset)
    dataset_scope = build_dataset_scope(dataset, cases)

    dry_results = _complete_results(cases, DEFAULT_SYSTEMS)
    for result in dry_results:
        result["mode"] = "dry-run"
        result["status"] = "dry_run"
        result["generated_chapter_count"] = 0
        result["chapter_complete"] = False
    dry_scope = build_execution_scope(
        dataset_scope,
        cases,
        DEFAULT_SYSTEMS,
        mode="dry-run",
        judge_enabled=False,
        results=dry_results,
    )
    assert dry_scope.coverage_status == "partial"
    assert any("dry-run" in reason for reason in dry_scope.coverage_reasons)
    assert not any("failed case-system" in reason for reason in dry_scope.coverage_reasons)
    assert not any("chapter shortfalls" in reason for reason in dry_scope.coverage_reasons)

    partial_cases = cases[:5]
    partial_scope = build_execution_scope(
        dataset_scope,
        partial_cases,
        DEFAULT_SYSTEMS[:2],
        mode="live",
        judge_enabled=True,
        results=_complete_results(partial_cases, DEFAULT_SYSTEMS[:2]),
    )
    assert partial_scope.coverage_status == "partial"
    assert any("missing dataset cases" in reason for reason in partial_scope.coverage_reasons)
    assert any("missing systems" in reason for reason in partial_scope.coverage_reasons)

    failed_results = _complete_results(cases, DEFAULT_SYSTEMS)
    failed_results[0]["status"] = "failed"
    failed_scope = build_execution_scope(
        dataset_scope,
        cases,
        DEFAULT_SYSTEMS,
        mode="live",
        judge_enabled=True,
        results=failed_results,
    )
    assert any("failed case-system results: 1" == reason for reason in failed_scope.coverage_reasons)

    short_results = _complete_results(cases, DEFAULT_SYSTEMS)
    short_results[0]["generated_chapter_count"] = 0
    short_results[0]["chapter_complete"] = False
    short_scope = build_execution_scope(
        dataset_scope,
        cases,
        DEFAULT_SYSTEMS,
        mode="live",
        judge_enabled=True,
        results=short_results,
    )
    assert any("chapter shortfalls: 1" == reason for reason in short_scope.coverage_reasons)


def test_complete_60_result_matrix_is_complete_even_when_judge_is_disabled() -> None:
    from eval.metrics import (
        DEFAULT_SYSTEMS,
        build_dataset_scope,
        build_execution_scope,
        load_dataset,
    )

    dataset = PROJECT_ROOT / "eval" / "datasets" / "flashnovel_eval_v1.jsonl"
    cases = load_dataset(dataset)
    dataset_scope = build_dataset_scope(dataset, cases)
    results = _complete_results(cases, DEFAULT_SYSTEMS)

    scope = build_execution_scope(
        dataset_scope,
        cases,
        DEFAULT_SYSTEMS,
        mode="live",
        judge_enabled=False,
        results=results,
    )

    assert len(results) == 60
    assert sum(result["target_chapter_count"] for result in results) == 84
    assert scope.coverage_status == "complete"
    assert scope.coverage_reasons == ()


def test_unimplemented_metrics_have_explicit_unavailable_reasons() -> None:
    from eval.metrics import unavailable_metric_registry

    unavailable = unavailable_metric_registry()

    assert set(unavailable) == {
        "memory_f1",
        "rewrite_improvement",
        "readability",
        "cost",
    }
    assert all(reason for reason in unavailable.values())
