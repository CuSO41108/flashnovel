# Data Model: 可信评测指标与报告

## DatasetScope

Represents the complete validated source dataset before filters.

| Field | Type | Rules |
| --- | --- | --- |
| `dataset_path` | string | Source JSONL path |
| `case_ids` | list[string] | Unique IDs in dataset order |
| `case_count` | integer | Number of valid cases |
| `target_chapters` | integer | Sum of normalized `max_chapters` |
| `tag_counts` | map[string, integer] | Count of cases carrying each tag |

Validation:

- case IDs must be non-empty and unique;
- omitted `max_chapters` normalizes to 1;
- explicit `max_chapters` must be a positive integer;
- current v1 dataset must produce `case_count=20` and `target_chapters=28`.

## ExecutionScope

Represents what this invocation selected and what result matrix it expected.

| Field | Type | Rules |
| --- | --- | --- |
| `case_ids` | list[string] | Selected case IDs |
| `case_count` | integer | Selected case count |
| `target_chapters` | integer | Sum for selected cases |
| `systems` | list[string] | Unique validated systems |
| `expected_result_count` | integer | `case_count * system_count` |
| `mode` | enum | `dry-run` or `live` |
| `judge_enabled` | boolean | True only when live judge calls requested |
| `coverage_status` | enum | `complete` or `partial` |
| `coverage_reasons` | list[string] | Deterministic missing/failed scope reasons |

Coverage transition:

```text
created -> partial
partial -> complete
```

`complete` requires a live run, the full DatasetScope, all declared Eval systems, successful
case-system results for the full expected matrix, and `generated_chapter_count >=
target_chapter_count` for every result. Failure, omission, or a chapter shortfall returns/keeps
`partial`. Judge and call-usage completeness are separate MetricResult statuses.

## MetricResult

Represents one auditable aggregate.

| Field | Type | Rules |
| --- | --- | --- |
| `name` | string | Stable metric key |
| `status` | enum | `complete`, `incomplete`, `unavailable` |
| `value` | number/null | Null unless a defensible value exists |
| `numerator` | number/null | Required for rates |
| `denominator` | integer | Eligible sample count |
| `observed_count` | integer | Eligible samples with usable data |
| `excluded_count` | integer | Samples excluded by applicability |
| `source` | string | Events, artifacts, snapshots, or judges |
| `applicability` | string | Eligibility rule |
| `limitations` | list[string] | Known interpretation boundaries |
| `reason` | string/null | Required for incomplete/unavailable |

Status rules:

- `complete`: all eligible samples have usable values;
- `incomplete`: at least one eligible sample has usable data and at least one is missing;
- `unavailable`: no eligible usable value exists or the metric is intentionally unimplemented;
- denominator zero never produces a numeric rate.

## MemorySnapshot

Semantic view captured before and after a full-workflow run.

| Category | Semantic fields |
| --- | --- |
| `summaries` | chapter, title, summary, key_events |
| `timeline` | chapter, sequence, event, participants, location |
| `relationships` | source, target, relationship, status, since_chapter |
| `foreshadows` | key, description, status, setup_chapter, payoff_chapter |
| `state_changes` | chapter, entity, attribute, before, after, reason |

Generated IDs, timestamps and non-semantic storage metadata do not participate in equality.

## MemoryDelta

| Field | Type | Rules |
| --- | --- | --- |
| `category` | enum | One of the five MemorySnapshot categories |
| `before_count` | integer | Semantic record count before run |
| `after_count` | integer | Semantic record count after run |
| `added_count` | integer | New semantic identities |
| `changed_count` | integer | Existing identities with changed semantic payload |
| `written` | boolean | True when added or changed count is positive |

## ContextUsage

Represents actual context-budget evidence for one generated chapter.

| Field | Type | Rules |
| --- | --- | --- |
| `chapter` | integer | Generated chapter |
| `budget` | integer | Requested context budget |
| `estimated_tokens` | integer/null | Actual Context Builder estimate |
| `source` | enum | `context_budget_metadata`, `actual_context_estimate`, `unavailable` |
| `passed` | boolean/null | Null when no actual context was captured |
| `reason` | string/null | Required when unavailable |

## LLMCallRecord

One record per actual provider request.

| Field | Type | Rules |
| --- | --- | --- |
| `call_id` | string | Unique within run |
| `case_id` | string/null | Set by Eval collector |
| `system` | string/null | Set by Eval collector |
| `run_id` | string/null | Runtime run ID when applicable |
| `stage` | string | Tool name, baseline generation, or judge name |
| `mode` | string | sync, stream, fallback reason, or judge |
| `model` | string/null | Response model or configured model |
| `status` | enum | `completed` or `failed` |
| `latency_ms` | number | Non-negative elapsed time |
| `usage_status` | enum | `complete`, `incomplete`, `unavailable` |
| `prompt_tokens` | integer/null | Never fabricated as zero |
| `completion_tokens` | integer/null | Never fabricated as zero |
| `total_tokens` | integer/null | Never fabricated as zero |
| `error_type` | string/null | Sanitized exception class |
| `error` | string/null | Sanitized message without credentials/body |

## CaseSystemResult

Contains identity, execution status, artifact references, actual ContextUsage entries,
MemoryDelta entries, LLMCallRecords, event/checkpoint applicability and judge outputs.
Paths always point inside the new run directory.

Required chapter coverage fields:

| Field | Type | Rules |
| --- | --- | --- |
| `target_chapter_count` | integer | Normalized case `max_chapters` |
| `generated_chapter_count` | integer | Chapters actually persisted/generated by this system |
| `chapter_complete` | boolean | True only when generated count reaches target count |

## EvaluationSummary

Root machine-readable result:

- schema and Eval version;
- creation timestamp and immutable run directory;
- DatasetScope and ExecutionScope;
- results by case-system;
- metrics grouped by system and tag;
- LLM call coverage using `attempted_count` (incremented before provider invocation) and
  `observed_count` (completed call records), plus the unavailable-metric registry;
- claim limitations and partial reasons.

Historical summaries are not migrated into this model.
