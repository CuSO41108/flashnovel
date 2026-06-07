from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping


METRIC_STATUSES = frozenset({"complete", "incomplete", "unavailable"})
COVERAGE_STATUSES = frozenset({"complete", "partial"})
EXECUTION_MODES = frozenset({"dry-run", "live"})
CALL_STATUSES = frozenset({"completed", "failed"})
USAGE_STATUSES = METRIC_STATUSES
MEMORY_CATEGORIES = frozenset(
    {"summaries", "timeline", "relationships", "foreshadows", "state_changes"}
)
CONTEXT_SOURCES = frozenset(
    {"context_budget_metadata", "actual_context_estimate", "unavailable"}
)


def _require_enum(field_name: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {choices}")


@dataclass(frozen=True)
class DatasetScope:
    dataset_path: str
    case_ids: tuple[str, ...]
    case_count: int
    target_chapters: int
    tag_counts: Mapping[str, int]


@dataclass(frozen=True)
class ExecutionScope:
    case_ids: tuple[str, ...]
    case_count: int
    target_chapters: int
    systems: tuple[str, ...]
    expected_result_count: int
    mode: str
    judge_enabled: bool
    coverage_status: str
    coverage_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_enum("mode", self.mode, EXECUTION_MODES)
        _require_enum("coverage_status", self.coverage_status, COVERAGE_STATUSES)


@dataclass(frozen=True)
class MetricResult:
    name: str
    status: str
    value: float | None
    numerator: float | None
    denominator: int
    observed_count: int
    excluded_count: int
    source: str
    applicability: str
    limitations: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_enum("status", self.status, METRIC_STATUSES)
        if self.status != "complete" and not self.reason:
            raise ValueError("reason is required for incomplete or unavailable metrics")


@dataclass(frozen=True)
class MemoryDelta:
    category: str
    before_count: int
    after_count: int
    added_count: int
    changed_count: int
    written: bool

    def __post_init__(self) -> None:
        _require_enum("category", self.category, MEMORY_CATEGORIES)


@dataclass(frozen=True)
class ContextUsage:
    chapter: int
    budget: int
    estimated_tokens: int | None
    source: str
    passed: bool | None
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_enum("source", self.source, CONTEXT_SOURCES)
        if self.source == "unavailable" and not self.reason:
            raise ValueError("reason is required when context usage is unavailable")


@dataclass(frozen=True)
class LLMCallRecord:
    call_id: str
    stage: str
    mode: str
    status: str
    latency_ms: float
    usage_status: str
    case_id: str | None = None
    system: str | None = None
    run_id: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error_type: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        _require_enum("status", self.status, CALL_STATUSES)
        _require_enum("usage_status", self.usage_status, USAGE_STATUSES)
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
