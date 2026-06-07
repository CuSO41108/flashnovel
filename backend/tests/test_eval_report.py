from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _metric(
    name: str,
    *,
    value,
    numerator,
    denominator: int,
    status: str = "complete",
    source: str = "fixture source",
    reason: str | None = None,
) -> dict:
    return {
        "name": name,
        "status": status,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "observed_count": denominator if status == "complete" else max(0, denominator - 1),
        "excluded_count": 0,
        "source": source,
        "applicability": "fixture samples",
        "limitations": [],
        "reason": reason,
    }


def _summary_fixture() -> dict:
    naive = {
        "result_count": 2,
        "hard_metrics": {
            "run_success_rate": _metric(
                "run_success_rate",
                value=1.0,
                numerator=2,
                denominator=2,
                source="run status",
            )
        },
        "soft_metrics": {
            "coverage_score": _metric(
                "coverage_score",
                value=0.9,
                numerator=1.8,
                denominator=2,
                source="coverage judge",
            ),
            "continuity_score": _metric(
                "continuity_score",
                value=0.8,
                numerator=1.6,
                denominator=2,
                source="continuity judge",
            ),
        },
        "llm_metrics": {
            "usage_coverage_rate": _metric(
                "usage_coverage_rate",
                value=0.5,
                numerator=1,
                denominator=2,
                status="incomplete",
                source="provider usage",
                reason="one call omitted usage",
            )
        },
    }
    structured = {
        **naive,
        "result_count": 1,
        "soft_metrics": {
            "coverage_score": _metric(
                "coverage_score",
                value=0.7,
                numerator=0.7,
                denominator=1,
                source="coverage judge",
            ),
            "continuity_score": _metric(
                "continuity_score",
                value=0.85,
                numerator=0.85,
                denominator=1,
                source="continuity judge",
            ),
        },
    }
    full = {
        **naive,
        "result_count": 1,
        "soft_metrics": {
            "coverage_score": _metric(
                "coverage_score",
                value=1.0,
                numerator=1,
                denominator=1,
                source="coverage judge",
            ),
            "continuity_score": _metric(
                "continuity_score",
                value=0.6,
                numerator=0.6,
                denominator=1,
                source="continuity judge",
            ),
        },
    }
    return {
        "eval_version": "v1",
        "summary_schema_version": "2.0",
        "created_at": "2026-06-07T00:00:00+00:00",
        "mode": "live",
        "dataset_scope": {
            "dataset_path": "eval/datasets/flashnovel_eval_v1.jsonl",
            "case_ids": ["case-1", "case-2"],
            "case_count": 2,
            "target_chapters": 6,
            "tag_counts": {"continuity": 1},
        },
        "execution_scope": {
            "case_ids": ["case-1", "case-2"],
            "case_count": 2,
            "target_chapters": 6,
            "systems": [
                "naive_recent_text",
                "structured_memory_only",
                "flashnovel_full",
            ],
            "expected_result_count": 6,
            "mode": "live",
            "judge_enabled": True,
            "coverage_status": "complete",
            "coverage_reasons": [],
        },
        "by_system": {
            "flashnovel_full": full,
            "structured_memory_only": structured,
            "naive_recent_text": naive,
        },
        "by_tag": {
            "continuity": {
                "flashnovel_full": full,
                "naive_recent_text": naive,
            }
        },
        "llm_calls": {
            "attempted_count": 4,
            "observed_count": 4,
            "records": [],
        },
        "unavailable_metrics": {
            "memory_f1": "No validated semantic matcher is implemented."
        },
        "results": [],
    }


def test_report_renders_system_metrics_in_stable_order_with_provenance() -> None:
    from eval.reporting import render_report

    report = render_report(_summary_fixture())

    naive_position = report.index("### `naive_recent_text`")
    structured_position = report.index("### `structured_memory_only`")
    full_position = report.index("### `flashnovel_full`")
    assert naive_position < structured_position < full_position
    assert "| Hard | `run_success_rate` | complete | 1.0000 | 2/2 | run status |" in report
    assert "| Soft | `coverage_score` | complete | 0.9000 | 2/2 | coverage judge |" in report
    assert "| LLM | `usage_coverage_rate` | incomplete | 0.5000 | 1/2 | provider usage; one call omitted usage |" in report


def test_report_renders_tag_comparison_call_completeness_and_unavailable_reason() -> None:
    from eval.reporting import render_report

    report = render_report(_summary_fixture())

    assert "## Tag Breakdown" in report
    assert "| continuity | `naive_recent_text` | 2 | 0.9000 | 0.8000 |" in report
    assert "| continuity | `flashnovel_full` | 1 | 1.0000 | 0.6000 |" in report
    assert "- Attempted provider calls: 4" in report
    assert "- Observed call records: 4" in report
    assert "| `memory_f1` | unavailable | No validated semantic matcher is implemented. |" in report


def test_partial_report_has_prominent_boundary_and_describes_lower_full_score() -> None:
    from eval.reporting import render_report

    summary = _summary_fixture()
    summary["execution_scope"]["coverage_status"] = "partial"
    summary["execution_scope"]["coverage_reasons"] = [
        "missing dataset cases: 15",
        "missing systems: structured_memory_only",
    ]

    report = render_report(summary)

    assert report.startswith("# FlashNovel Eval Report [PARTIAL]")
    assert "## Executive Summary" in report
    assert "- Coverage status: **partial**" in report
    assert "missing dataset cases: 15" in report
    assert (
        "FlashNovel full continuity (0.6000) is below "
        "structured_memory_only (0.8500)."
    ) in report
    assert "明显提升" not in report
    assert "证明更优" not in report
