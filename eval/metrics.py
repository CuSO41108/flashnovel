from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval.models import DatasetScope, ExecutionScope, MemoryDelta, MetricResult


DEFAULT_SYSTEMS = ("naive_recent_text", "structured_memory_only", "flashnovel_full")
REQUIRED_CASE_FIELDS = {
    "id",
    "difficulty",
    "tags",
    "story",
    "seed_memory",
    "recent_context",
    "run",
    "oracle",
}
MEMORY_FIELDS = {
    "summaries": (
        ("chapter",),
        ("chapter", "title", "summary", "key_events"),
        (("chapter_summaries",), ("summaries",), ("episodic", "recent_summaries")),
    ),
    "timeline": (
        ("chapter", "sequence"),
        ("chapter", "sequence", "event", "participants", "location"),
        (("timeline",), ("episodic", "timeline")),
    ),
    "relationships": (
        ("source", "target"),
        ("source", "target", "relationship", "status", "since_chapter"),
        (("relationships",), ("continuity", "relationships")),
    ),
    "foreshadows": (
        ("key",),
        ("key", "description", "status", "setup_chapter", "payoff_chapter"),
        (("foreshadows",), ("continuity", "foreshadows")),
    ),
    "state_changes": (
        ("chapter", "entity", "attribute"),
        ("chapter", "entity", "attribute", "before", "after", "reason"),
        (("state_changes",), ("continuity", "state_changes")),
    ),
}


def load_dataset(dataset: Path) -> list[dict[str, Any]]:
    path = Path(dataset)
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"dataset line {line_no} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"dataset line {line_no} must be a JSON object")
        case = _validate_case(raw, line_no)
        case_id = str(case["id"])
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        cases.append(case)
    if not cases:
        raise ValueError("eval dataset is empty")
    return cases


def _validate_case(raw: Mapping[str, Any], line_no: int) -> dict[str, Any]:
    missing = REQUIRED_CASE_FIELDS.difference(raw)
    if missing:
        fields = ", ".join(sorted(missing))
        raise ValueError(f"dataset line {line_no} missing fields: {fields}")
    case_id = str(raw.get("id") or "").strip()
    if not case_id:
        raise ValueError(f"dataset line {line_no} has an empty case id")
    oracle = raw.get("oracle")
    if not isinstance(oracle, Mapping) or not oracle.get("must_cover") or not oracle.get("must_not"):
        raise ValueError(
            f"dataset line {line_no} must include non-empty oracle.must_cover and oracle.must_not"
        )
    run = raw.get("run")
    if not isinstance(run, Mapping):
        raise ValueError(f"dataset line {line_no} run must be an object")
    max_chapters = run.get("max_chapters", 1)
    if isinstance(max_chapters, bool) or not isinstance(max_chapters, int) or max_chapters <= 0:
        raise ValueError(
            f"dataset line {line_no} max_chapters must be a positive integer"
        )
    normalized = dict(raw)
    normalized["id"] = case_id
    normalized["run"] = {**run, "max_chapters": max_chapters}
    normalized["tags"] = list(raw.get("tags") or [])
    return normalized


def build_dataset_scope(dataset: Path, cases: Sequence[Mapping[str, Any]]) -> DatasetScope:
    tag_counts = Counter(
        str(tag)
        for case in cases
        for tag in (case.get("tags") or [])
        if str(tag).strip()
    )
    return DatasetScope(
        dataset_path=str(Path(dataset)),
        case_ids=tuple(str(case["id"]) for case in cases),
        case_count=len(cases),
        target_chapters=sum(_target_chapters(case) for case in cases),
        tag_counts=dict(sorted(tag_counts.items())),
    )


def build_execution_scope(
    dataset_scope: DatasetScope,
    selected_cases: Sequence[Mapping[str, Any]],
    systems: Sequence[str],
    *,
    mode: str,
    judge_enabled: bool,
    results: Sequence[Mapping[str, Any]],
) -> ExecutionScope:
    normalized_systems = validate_systems(systems)
    case_ids = tuple(str(case["id"]) for case in selected_cases)
    target_chapters = sum(_target_chapters(case) for case in selected_cases)
    reasons: list[str] = []
    if mode != "live":
        reasons.append("dry-run does not provide live coverage")

    dataset_ids = set(dataset_scope.case_ids)
    selected_ids = set(case_ids)
    missing_cases = dataset_ids.difference(selected_ids)
    if missing_cases:
        reasons.append(f"missing dataset cases: {len(missing_cases)}")
    extra_cases = selected_ids.difference(dataset_ids)
    if extra_cases:
        reasons.append(f"unknown selected cases: {len(extra_cases)}")

    missing_systems = [
        system for system in DEFAULT_SYSTEMS if system not in normalized_systems
    ]
    if missing_systems:
        reasons.append(f"missing systems: {', '.join(missing_systems)}")

    if mode == "live":
        expected_pairs = {
            (case_id, system)
            for case_id in case_ids
            for system in normalized_systems
        }
        result_pairs = [
            (str(result.get("case_id")), str(result.get("system")))
            for result in results
        ]
        unique_result_pairs = set(result_pairs)
        missing_pairs = expected_pairs.difference(unique_result_pairs)
        if missing_pairs:
            reasons.append(f"missing case-system results: {len(missing_pairs)}")
        duplicate_count = len(result_pairs) - len(unique_result_pairs)
        if duplicate_count:
            reasons.append(f"duplicate case-system results: {duplicate_count}")

        successful_statuses = {"completed", "awaiting_confirmation"}
        relevant_results = [
            result
            for result in results
            if (str(result.get("case_id")), str(result.get("system"))) in expected_pairs
        ]
        failed_count = sum(
            1
            for result in relevant_results
            if str(result.get("status")) not in successful_statuses
        )
        if failed_count:
            reasons.append(f"failed case-system results: {failed_count}")
        chapter_shortfalls = sum(
            1
            for result in relevant_results
            if int(result.get("generated_chapter_count") or 0)
            < int(result.get("target_chapter_count") or 1)
        )
        if chapter_shortfalls:
            reasons.append(f"chapter shortfalls: {chapter_shortfalls}")

    coverage_status = "complete" if not reasons else "partial"
    return ExecutionScope(
        case_ids=case_ids,
        case_count=len(case_ids),
        target_chapters=target_chapters,
        systems=normalized_systems,
        expected_result_count=len(case_ids) * len(normalized_systems),
        mode=mode,
        judge_enabled=judge_enabled,
        coverage_status=coverage_status,
        coverage_reasons=tuple(reasons),
    )


def unavailable_metric_registry() -> dict[str, str]:
    return {
        "memory_f1": "No validated semantic matcher is implemented.",
        "rewrite_improvement": "No reliable before/after rewrite quality labels are available.",
        "readability": "No validated readability rubric output is collected.",
        "cost": "Model pricing provenance is not configured for observed calls.",
    }


def select_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    case_ids: Sequence[str] = (),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be a positive integer")
    requested = tuple(str(case_id) for case_id in case_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate case ids were selected")
    available = {str(case["id"]) for case in cases}
    unknown = [case_id for case_id in requested if case_id not in available]
    if unknown:
        raise ValueError(f"unknown case ids: {', '.join(unknown)}")
    requested_set = set(requested)
    selected = [
        dict(case)
        for case in cases
        if not requested_set or str(case["id"]) in requested_set
    ]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no eval cases selected")
    return selected


def validate_systems(
    systems: Sequence[str],
    *,
    declared_systems: Sequence[str] = DEFAULT_SYSTEMS,
) -> tuple[str, ...]:
    normalized = tuple(str(system).strip() for system in systems if str(system).strip())
    if not normalized:
        raise ValueError("at least one eval system must be selected")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate eval systems are not allowed")
    allowed = set(declared_systems)
    unknown = [system for system in normalized if system not in allowed]
    if unknown:
        raise ValueError(f"unknown eval systems: {', '.join(unknown)}")
    return normalized


def aggregate_hard_metrics(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, MetricResult]:
    live_results = [item for item in results if item.get("mode") == "live"]
    full_live = [
        item for item in live_results if item.get("system") == "flashnovel_full"
    ]
    checkpoint_results = [
        item for item in full_live if int(item.get("target_chapter_count") or 0) > 1
    ]
    budgeted_results = [
        item for item in live_results if int(item.get("context_budget") or 0) > 0
    ]

    return {
        "run_success_rate": _boolean_metric(
            name="run_success_rate",
            values=[
                str(item.get("status")) in {"completed", "awaiting_confirmation"}
                for item in live_results
            ],
            total_count=len(results),
            source="run status",
            applicability="live case-system results",
        ),
        "artifact_exists_rate": _boolean_metric(
            name="artifact_exists_rate",
            values=[bool(item.get("artifact_exists")) for item in live_results],
            total_count=len(results),
            source="chapter artifacts",
            applicability="live case-system results",
        ),
        "event_complete_rate": _boolean_metric(
            name="event_complete_rate",
            values=[item.get("event_complete") for item in full_live],
            total_count=len(results),
            source="runtime events",
            applicability="live flashnovel_full results",
        ),
        "checkpoint_rate": _boolean_metric(
            name="checkpoint_rate",
            values=[item.get("checkpoint_created") for item in checkpoint_results],
            total_count=len(results),
            source="checkpoint.created events",
            applicability="live multi-chapter flashnovel_full results",
        ),
        "token_budget_pass_rate": _boolean_metric(
            name="token_budget_pass_rate",
            values=[_context_budget_passed(item) for item in budgeted_results],
            total_count=len(results),
            source="actual model input or Context Builder artifacts",
            applicability="live results with a positive context budget",
        ),
        "memory_write_rate": _boolean_metric(
            name="memory_write_rate",
            values=[item.get("memory_written") for item in full_live],
            total_count=len(results),
            source="semantic memory before/after deltas",
            applicability="live flashnovel_full results with memory snapshots",
        ),
    }


def _boolean_metric(
    *,
    name: str,
    values: Sequence[Any],
    total_count: int,
    source: str,
    applicability: str,
) -> MetricResult:
    denominator = len(values)
    observed = [bool(value) for value in values if value is not None]
    observed_count = len(observed)
    numerator = sum(1 for value in observed if value)
    excluded_count = max(0, total_count - denominator)
    if denominator == 0:
        return MetricResult(
            name=name,
            status="unavailable",
            value=None,
            numerator=None,
            denominator=0,
            observed_count=0,
            excluded_count=excluded_count,
            source=source,
            applicability=applicability,
            reason=f"no eligible {applicability}",
        )
    if observed_count == 0:
        return MetricResult(
            name=name,
            status="unavailable",
            value=None,
            numerator=None,
            denominator=denominator,
            observed_count=0,
            excluded_count=excluded_count,
            source=source,
            applicability=applicability,
            reason="eligible records have no observed values",
        )
    status = "complete" if observed_count == denominator else "incomplete"
    return MetricResult(
        name=name,
        status=status,
        value=round(numerator / denominator, 4),
        numerator=numerator,
        denominator=denominator,
        observed_count=observed_count,
        excluded_count=excluded_count,
        source=source,
        applicability=applicability,
        reason=None if status == "complete" else "some eligible records have no observed value",
    )


def _context_budget_passed(result: Mapping[str, Any]) -> bool | None:
    usages = result.get("context_usages")
    if not isinstance(usages, Sequence) or isinstance(usages, (str, bytes)) or not usages:
        return None
    values = [
        item.get("passed")
        for item in usages
        if isinstance(item, Mapping)
    ]
    if not values or any(value is None for value in values):
        return None
    return all(bool(value) for value in values)


def calculate_memory_deltas(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[MemoryDelta, ...]:
    deltas: list[MemoryDelta] = []
    for category in MEMORY_FIELDS:
        before_records = _semantic_memory_records(before, category)
        after_records = _semantic_memory_records(after, category)
        added_keys = set(after_records).difference(before_records)
        changed_keys = {
            key
            for key in set(before_records).intersection(after_records)
            if before_records[key] != after_records[key]
        }
        added_count = len(added_keys)
        changed_count = len(changed_keys)
        deltas.append(
            MemoryDelta(
                category=category,
                before_count=len(before_records),
                after_count=len(after_records),
                added_count=added_count,
                changed_count=changed_count,
                written=bool(added_count or changed_count),
            )
        )
    return tuple(deltas)


def memory_was_written(deltas: Sequence[MemoryDelta]) -> bool:
    return any(delta.written for delta in deltas)


def aggregate_by_system(
    results: Sequence[Mapping[str, Any]],
    *,
    systems: Sequence[str] = DEFAULT_SYSTEMS,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for system in systems:
        system_results = [
            result for result in results if str(result.get("system")) == system
        ]
        grouped[system] = _metric_group(system_results)
    return grouped


def aggregate_by_tag(
    results: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    *,
    systems: Sequence[str] = DEFAULT_SYSTEMS,
) -> dict[str, dict[str, dict[str, Any]]]:
    tags_by_case = {
        str(case["id"]): tuple(str(tag) for tag in (case.get("tags") or []))
        for case in cases
    }
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for tag in sorted({tag for tags in tags_by_case.values() for tag in tags}):
        tag_results = [
            result
            for result in results
            if tag in tags_by_case.get(str(result.get("case_id")), ())
        ]
        system_groups: dict[str, dict[str, Any]] = {}
        for system in systems:
            system_results = [
                result
                for result in tag_results
                if str(result.get("system")) == system
            ]
            if system_results:
                system_groups[system] = _metric_group(system_results)
        grouped[tag] = system_groups
    return grouped


def _metric_group(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "result_count": len(results),
        "hard_metrics": aggregate_hard_metrics(results),
        "soft_metrics": {
            "coverage_score": _soft_metric(results, "coverage_score"),
            "continuity_score": _soft_metric(results, "continuity_score"),
            "contradiction_count": _soft_metric(results, "contradiction_count"),
        },
        "llm_metrics": _llm_metrics(results),
    }


def _soft_metric(
    results: Sequence[Mapping[str, Any]],
    name: str,
) -> MetricResult:
    live_results = [result for result in results if result.get("mode") == "live"]
    values = [_judge_value(result, name) for result in live_results]
    return _numeric_metric(
        name=name,
        values=values,
        total_count=len(results),
        source="LLM judge outputs",
        applicability=f"live results with {name} judge output",
    )


def _judge_value(result: Mapping[str, Any], name: str) -> float | None:
    judges = result.get("judges")
    if not isinstance(judges, Mapping):
        return None
    continuity_entry = judges.get("continuity")
    coverage_entry = judges.get("coverage")
    continuity = (
        continuity_entry.get("result")
        if isinstance(continuity_entry, Mapping)
        else None
    )
    coverage = (
        coverage_entry.get("result")
        if isinstance(coverage_entry, Mapping)
        else None
    )
    sources = (coverage, continuity) if name == "coverage_score" else (continuity, coverage)
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        value = source.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _llm_metrics(results: Sequence[Mapping[str, Any]]) -> dict[str, MetricResult]:
    calls = [
        call
        for result in results
        for call in (result.get("llm_calls") or [])
        if isinstance(call, Mapping)
    ]
    attempted_count = sum(int(result.get("llm_attempted_count") or 0) for result in results)
    observed_count = len(calls)
    call_coverage = _ratio_metric(
        name="call_record_coverage",
        numerator=observed_count,
        denominator=attempted_count,
        source="EvalClient counters and runtime llm.call events",
        applicability="actual provider requests",
    )
    usage_coverage = _boolean_metric(
        name="usage_coverage_rate",
        values=[call.get("usage_status") == "complete" for call in calls],
        total_count=observed_count,
        source="LLM call records",
        applicability="observed provider calls",
    )
    latency = _numeric_metric(
        name="average_latency_ms",
        values=[
            _number_or_none(call.get("latency_ms"))
            for call in calls
        ],
        total_count=observed_count,
        source="monotonic request timers",
        applicability="observed provider calls",
    )
    total_tokens = _numeric_metric(
        name="average_total_tokens",
        values=[
            _number_or_none(call.get("total_tokens"))
            for call in calls
        ],
        total_count=observed_count,
        source="provider usage payloads",
        applicability="observed provider calls with total token usage",
    )
    return {
        "call_record_coverage": call_coverage,
        "usage_coverage_rate": usage_coverage,
        "average_latency_ms": latency,
        "average_total_tokens": total_tokens,
    }


def _ratio_metric(
    *,
    name: str,
    numerator: int,
    denominator: int,
    source: str,
    applicability: str,
) -> MetricResult:
    if denominator == 0:
        return MetricResult(
            name=name,
            status="unavailable",
            value=None,
            numerator=None,
            denominator=0,
            observed_count=0,
            excluded_count=0,
            source=source,
            applicability=applicability,
            reason=f"no eligible {applicability}",
        )
    status = "complete" if numerator == denominator else "incomplete"
    return MetricResult(
        name=name,
        status=status,
        value=round(numerator / denominator, 4),
        numerator=numerator,
        denominator=denominator,
        observed_count=numerator,
        excluded_count=0,
        source=source,
        applicability=applicability,
        reason=None if status == "complete" else "some provider requests lack call records",
    )


def _numeric_metric(
    *,
    name: str,
    values: Sequence[float | None],
    total_count: int,
    source: str,
    applicability: str,
) -> MetricResult:
    denominator = len(values)
    observed = [value for value in values if value is not None]
    observed_count = len(observed)
    excluded_count = max(0, total_count - denominator)
    if denominator == 0 or observed_count == 0:
        return MetricResult(
            name=name,
            status="unavailable",
            value=None,
            numerator=None,
            denominator=denominator,
            observed_count=observed_count,
            excluded_count=excluded_count,
            source=source,
            applicability=applicability,
            reason=(
                f"no eligible {applicability}"
                if denominator == 0
                else "eligible records have no observed values"
            ),
        )
    total = sum(observed)
    status = "complete" if observed_count == denominator else "incomplete"
    return MetricResult(
        name=name,
        status=status,
        value=round(total / observed_count, 4),
        numerator=round(total, 4),
        denominator=denominator,
        observed_count=observed_count,
        excluded_count=excluded_count,
        source=source,
        applicability=applicability,
        reason=None if status == "complete" else "some eligible records have no observed value",
    )


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _semantic_memory_records(
    memory: Mapping[str, Any],
    category: str,
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    identity_fields, semantic_fields, paths = MEMORY_FIELDS[category]
    records: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for path in paths:
        value: Any = memory
        for part in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(part)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            continue
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                continue
            identity = tuple(_canonical(item.get(field)) for field in identity_fields)
            if not any(part not in (None, "") for part in identity):
                identity = ("__index__", index, _canonical(dict(item)))
            payload = tuple(_canonical(item.get(field)) for field in semantic_fields)
            records[identity] = payload
    return records


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _canonical(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_canonical(item) for item in value)
    return value


def _target_chapters(case: Mapping[str, Any]) -> int:
    return int((case.get("run") or {}).get("max_chapters") or 1)
