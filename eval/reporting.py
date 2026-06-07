from __future__ import annotations

from typing import Any, Mapping


SYSTEM_ORDER = (
    "naive_recent_text",
    "structured_memory_only",
    "flashnovel_full",
)


def render_report(summary: Mapping[str, Any]) -> str:
    execution = summary.get("execution_scope")
    execution_scope = execution if isinstance(execution, Mapping) else {}
    status = str(execution_scope.get("coverage_status") or "partial")
    reasons = execution_scope.get("coverage_reasons") or []
    dataset = summary.get("dataset_scope")
    dataset_scope = dataset if isinstance(dataset, Mapping) else {}
    by_system = summary.get("by_system")
    system_groups = by_system if isinstance(by_system, Mapping) else {}
    lines = [
        f"# FlashNovel Eval Report [{status.upper()}]",
        "",
        f"- Coverage status: **{status}**",
        f"- Mode: `{summary.get('mode', 'unknown')}`",
    ]
    if reasons:
        lines.append(f"- Coverage limitations: {'; '.join(str(reason) for reason in reasons)}")
    else:
        lines.append("- Coverage limitations: none")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            f"- Dataset cases: {dataset_scope.get('case_count', summary.get('case_count', 0))}",
            f"- Dataset target chapters: {dataset_scope.get('target_chapters', 'unavailable')}",
            f"- Executed cases: {execution_scope.get('case_count', summary.get('case_count', 0))}",
            f"- Executed target chapters: {execution_scope.get('target_chapters', 'unavailable')}",
            "",
            "## Executive Summary",
            "",
            f"- Coverage status: **{status}**",
        ]
    )
    lines.extend(f"- {finding}" for finding in _descriptive_findings(system_groups))
    lines.extend(
        [
            "- Findings below are descriptive only and do not assert an unverified winner.",
            "",
            "## Per-System Results",
            "",
        ]
    )
    for system in _ordered_systems(system_groups):
        group = system_groups.get(system)
        if not isinstance(group, Mapping):
            continue
        lines.extend(
            [
                f"### `{system}`",
                "",
                f"- Result count: {group.get('result_count', 0)}",
                "",
                "| Category | Metric | Status | Value | Sample | Source / Reason |",
                "| --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for category, key in (
            ("Hard", "hard_metrics"),
            ("Soft", "soft_metrics"),
            ("LLM", "llm_metrics"),
        ):
            metrics = group.get(key)
            if not isinstance(metrics, Mapping):
                continue
            for name, metric in metrics.items():
                if not isinstance(metric, Mapping):
                    continue
                lines.append(_metric_row(category, str(name), metric))
        lines.append("")

    lines.extend(
        [
            "## Tag Breakdown",
            "",
            "| Tag | System | Cases | Coverage | Continuity |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    by_tag = summary.get("by_tag")
    tag_groups = by_tag if isinstance(by_tag, Mapping) else {}
    for tag in sorted(str(name) for name in tag_groups):
        groups = tag_groups.get(tag)
        if not isinstance(groups, Mapping):
            continue
        for system in _ordered_systems(groups):
            group = groups.get(system)
            if not isinstance(group, Mapping):
                continue
            soft = group.get("soft_metrics")
            soft_metrics = soft if isinstance(soft, Mapping) else {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        tag,
                        f"`{system}`",
                        str(group.get("result_count", 0)),
                        _metric_value(soft_metrics.get("coverage_score")),
                        _metric_value(soft_metrics.get("continuity_score")),
                    ]
                )
                + " |"
            )

    calls = summary.get("llm_calls")
    llm_calls = calls if isinstance(calls, Mapping) else {}
    lines.extend(
        [
            "",
            "## LLM Call Completeness",
            "",
            f"- Attempted provider calls: {llm_calls.get('attempted_count', summary.get('live_llm_calls', 0))}",
            f"- Observed call records: {llm_calls.get('observed_count', 0)}",
            "",
            "## Unavailable Metrics",
            "",
            "| Metric | Status | Reason |",
            "| --- | --- | --- |",
        ]
    )
    unavailable = summary.get("unavailable_metrics")
    unavailable_metrics = unavailable if isinstance(unavailable, Mapping) else {}
    for name in sorted(str(key) for key in unavailable_metrics):
        lines.append(
            f"| `{name}` | unavailable | {unavailable_metrics.get(name)} |"
        )
    if not unavailable_metrics:
        lines.append("| none | complete | No unavailable metrics were declared. |")
    lines.extend(
        [
            "",
            "## Result Inventory",
            "",
            "| Case | System | Status | Chapters |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for result in summary.get("results") or []:
        if not isinstance(result, Mapping):
            continue
        generated = result.get("generated_chapter_count", 0)
        target = result.get("target_chapter_count", "?")
        lines.append(
            f"| {result.get('case_id')} | {result.get('system')} | "
            f"{result.get('status')} | {generated}/{target} |"
        )
    configuration = summary.get("configuration")
    config = configuration if isinstance(configuration, Mapping) else {}
    lines.extend(
        [
            "",
            "## Reproducibility Notes",
            "",
            f"- Dataset: `{config.get('dataset', 'unavailable')}`",
            f"- Systems: {', '.join(str(item) for item in (config.get('systems') or []))}",
            f"- Mode: `{config.get('mode', summary.get('mode', 'unknown'))}`",
            f"- Judge enabled: {config.get('judge_enabled', False)}",
            f"- Limit: {config.get('limit')}",
            f"- Selected case IDs: {', '.join(str(item) for item in (config.get('case_ids') or [])) or 'all'}",
        ]
    )
    return "\n".join(lines) + "\n"


def _ordered_systems(groups: Mapping[str, Any]) -> list[str]:
    available = {str(system) for system in groups}
    ordered = [system for system in SYSTEM_ORDER if system in available]
    ordered.extend(sorted(available.difference(ordered)))
    return ordered


def _metric_row(category: str, name: str, metric: Mapping[str, Any]) -> str:
    observed = metric.get("observed_count", 0)
    denominator = metric.get("denominator", 0)
    source = str(metric.get("source") or "unavailable")
    reason = metric.get("reason")
    detail = f"{source}; {reason}" if reason else source
    return (
        f"| {category} | `{name}` | {metric.get('status', 'unavailable')} | "
        f"{_metric_value(metric)} | {observed}/{denominator} | {detail} |"
    )


def _metric_value(metric: Any) -> str:
    if not isinstance(metric, Mapping):
        return "unavailable"
    value = metric.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.4f}"
    return "unavailable"


def _descriptive_findings(groups: Mapping[str, Any]) -> list[str]:
    full_value = _system_metric_value(
        groups,
        "flashnovel_full",
        "soft_metrics",
        "continuity_score",
    )
    if full_value is None:
        return ["Continuity comparison is unavailable for FlashNovel full."]
    findings: list[str] = []
    for baseline in ("naive_recent_text", "structured_memory_only"):
        baseline_value = _system_metric_value(
            groups,
            baseline,
            "soft_metrics",
            "continuity_score",
        )
        if baseline_value is None:
            continue
        relation = "below" if full_value < baseline_value else "above"
        if full_value == baseline_value:
            relation = "equal to"
        findings.append(
            f"FlashNovel full continuity ({full_value:.4f}) is {relation} "
            f"{baseline} ({baseline_value:.4f})."
        )
    return findings or ["No baseline continuity comparison is available."]


def _system_metric_value(
    groups: Mapping[str, Any],
    system: str,
    category: str,
    metric_name: str,
) -> float | None:
    group = groups.get(system)
    if not isinstance(group, Mapping):
        return None
    metrics = group.get(category)
    if not isinstance(metrics, Mapping):
        return None
    metric = metrics.get(metric_name)
    if not isinstance(metric, Mapping):
        return None
    value = metric.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
