# Implementation Plan: 可信评测指标与报告

**Branch**: `001-trustworthy-eval-report` | **Date**: 2026-06-07 |
**Spec**: [spec.md](spec.md)

**Input**: Feature specification from
`/specs/001-trustworthy-eval-report/spec.md`

## Summary

将当前单体 Eval runner 拆出纯数据模型、指标聚合和报告渲染边界，准确区分完整数据集、
本次执行范围、运行覆盖状态与单项指标可用性。完整工作流继续使用当前同步 Tool 注册路径，
仅增加局部 LLM 调用观测；memory write 使用运行前后快照差异，token budget 使用本次运行
保存的实际 Context Builder 上下文。所有变更按失败测试、最小实现、回归验证的顺序完成，
历史结果目录保持不可变，完整 live 评测只作为人工预算批准后的发布门槛。

## Technical Context

**Language/Version**: Python >=3.10（当前开发环境 Python 3.13.1）

**Primary Dependencies**: Python 标准库、现有 FastAPI/LangGraph runtime、
OpenAI-compatible LLM client；不新增运行时依赖

**Storage**: JSONL 数据集、每次运行独立的 JSON/Markdown 结果目录；完整工作流继续使用
临时 SQLite 与文件 Artifact Store

**Testing**: pytest，纯指标单元测试、报告结构测试、runner 集成测试、同步 Tool
调用观测回归测试

**Target Platform**: Windows PowerShell 本地开发；Python CLI 可在其他受支持平台运行

**Project Type**: Python web service + Agent runtime + 本地评测 CLI

**Performance Goals**: 普通测试和 dry-run 发起 0 次真实模型调用；聚合和报告时间相对
模型运行可忽略；20-case 数据集可一次性在内存中聚合

**Constraints**: 测试驱动；不覆盖历史结果；不提交 `eval/results/`；完整 live 运行必须
人工确认预算；不统一 Tool、不修改 Run 状态所有权、不拆 Store

**Scale/Scope**: 当前 20 cases、28 target chapters、3 systems；设计允许同规模数据集
继续扩展，但本轮不建设通用评测平台

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research

- **Evidence scope — PASS**: 计划分别记录 dataset scope、execution scope、coverage status
  与 metric status；partial 结果不能生成效果提升结论。
- **Metric provenance — PASS**: 每个 rate 使用结构化 MetricResult，包含 numerator、
  denominator、source、applicability、exclusions、limitations 和 status。
- **Execution path — PASS**: `app.tools.build_tool_registry` 与现有同步 Tool 路径保持不变；
  只在该路径增加调用观测。
- **State ownership — PASS**: 不修改 Run 状态转换、Registry、Graph 路由或恢复语义。
- **Incremental scope — PASS**: 先提取 Eval 纯函数边界，再接入 runner；不进行架构重构。
- **Verification — PASS**: 每类已确认缺陷先增加失败测试，再实现最小修复；最终运行完整
  后端测试和无付费 dry-run。
- **Repository safety — PASS**: 新运行使用唯一目录；历史目录只读；不包含批量删除操作。

### Post-Design

- **Evidence scope — PASS**: `EvaluationSummary` 与报告契约禁止用单项缺失数据推断整体效果。
- **Metric provenance — PASS**: [data-model.md](data-model.md) 定义完整指标状态与分母模型。
- **Execution path — PASS**: [research.md](research.md) 选择兼容的 `llm.call` 事件扩展，
  不改变正式 Tool 注册。
- **State ownership — PASS**: 设计未引入状态写入点。
- **Incremental scope — PASS**: 文件职责和迁移顺序独立可测。
- **Verification — PASS**: [quickstart.md](quickstart.md) 将自动验证与人工 live gate 分离。
- **Repository safety — PASS**: [contracts/output-contract.md](contracts/output-contract.md)
  明确原始结果和可提交摘要边界。

## Project Structure

### Documentation (this feature)

```text
specs/001-trustworthy-eval-report/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── eval-summary.schema.json
│   └── output-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
eval/
├── datasets/flashnovel_eval_v1.jsonl
├── reports/eval_report_template.md
├── models.py              # Eval records and JSON serialization contracts
├── metrics.py             # Pure scope, delta, applicability, and aggregation logic
├── reporting.py           # Markdown report generation from summary data
├── run_eval.py            # CLI, orchestration, runtime collection, artifact writing
└── README.md

backend/
├── app/
│   ├── graph/nodes.py            # Pass existing run identity to observed Tool calls
│   └── tools/sync_tools.py
└── tests/
    ├── test_eval_metrics.py
    ├── test_eval_report.py
    ├── test_eval_runner.py
    └── test_runtime_recovery_and_budget.py
```

**Structure Decision**: Eval-specific models, metrics and reporting remain under `eval/` so the
runtime does not depend on evaluation code. `run_eval.py` retains orchestration and runtime
integration. The only production-path edit is call observability in
`backend/app/tools/sync_tools.py`; existing runtime and Store boundaries remain unchanged.

## Design

### 1. Dataset And Execution Scope

Load and validate the entire dataset before applying `--case-id` or `--limit`. Build
`DatasetScope` from all valid cases and `ExecutionScope` from selected cases and systems.
Reject explicit non-positive or non-integer `max_chapters`; treat an omitted value as one chapter.
The current dataset must resolve to 20 cases and 28 target chapters.

### 2. Coverage And Metric Status

Use separate status dimensions:

- `coverage_status`: `complete` only for a live run whose successful result matrix covers every
  dataset case and all three declared systems, and whose every case-system result generated the
  requested `max_chapters`; otherwise `partial` with reasons.
- `metric_status`: `complete`, `incomplete`, or `unavailable` for each metric.
- Missing provider usage makes token/cost metrics incomplete, but does not rewrite successful
  Coverage or Continuity results. Reports still show the missing-data warning and prohibit claims
  that rely on the incomplete metric.

Dry-run remains useful for prompt/layout validation but is always non-publishable and excluded
from live-only metric denominators.

### 3. Metric Calculation

All rate metrics return `MetricResult`, never a bare float. Eligibility rules are explicit:

- run success and event completeness: live results only;
- checkpoint: live `flashnovel_full` results whose case requests more than one chapter;
- memory write: live `flashnovel_full` results with both before and after memory snapshots;
- token budget: results with an actual recorded input/context and a positive budget;
- soft metrics: records with a successful judge result for that metric.

Aggregate first by system, then by tag. A cross-system overall block may remain diagnostic but
cannot replace per-system tables.

### 4. Memory Delta

Capture `memory_before` after all seed and recent-context injection and before run creation.
Capture `memory_after` after execution. Compare semantic fields for chapter summaries, timeline,
relationships, foreshadows, and state changes while ignoring IDs and timestamps. A category is
written only when a semantic record is added or changed; seed presence alone is not a write.

### 5. Actual Context Budget

For `flashnovel_full`, read the `kind="prompt"` artifact written by `plan_chapter`. Its `context`
field is the actual Context Builder output passed to planning and drafting. Record per-chapter
budget, actual estimated tokens from `_context_budget` when present, and a deterministic fallback
estimate of that same context when metadata is absent. If execution fails before context capture,
the metric is unavailable with a reason.

Baseline systems continue to measure their rendered generation prompts because those are their
actual model inputs.

### 6. LLM Call Observability

Add one `llm.call` event for every actual sync or streaming request made by the official
`sync_tools.py` path. Each event contains call identity, tool, mode, model, status, latency,
usage availability, returned usage when present, and sanitized error type/message when failed.
Retain the existing `llm.usage` compatibility event when usage is available so the current UI
and consumers do not regress.

The Eval client records equivalent call entries for baseline and judge calls. Full-workflow
results derive call records from `llm.call` events, including failed attempts and fallback calls.
A failed/empty stream followed by a completion fallback is two provider requests and therefore
must produce two call records.

### 7. Reporting And Historical Results

Generate summary and report only inside the newly created unique run directory. Never update or
reinterpret an existing result directory in place. The report displays:

- prominent complete/partial coverage status and reasons;
- full dataset scope versus execution scope;
- per-system hard and soft metrics with numerator/denominator/status;
- per-tag system comparison;
- LLM call coverage, latency and usage completeness;
- explicit `unavailable`/`incomplete` rows for memory F1, rewrite improvement, readability and
  cost until reliable inputs exist;
- descriptive findings only, with no prewritten “FlashNovel is better” conclusion.

## Implementation Sequence

1. Add failing pure tests for dataset scope, MetricResult denominators, dry-run exclusion,
   checkpoint applicability and memory semantic deltas.
2. Implement Eval models and pure metric functions until those tests pass.
3. Add failing report tests for partial banners, per-system tables, unavailable fields and
   non-prescriptive conclusions.
4. Implement report rendering and replace the misleading report template text.
5. Add failing sync Tool tests for success, missing usage, streaming, fallback and error call
   records.
6. Implement compatible LLM call observation without changing Tool registration.
7. Add failing runner tests for actual context artifacts, memory before/after snapshots, complete
   versus partial matrices and retained historical directories.
8. Integrate collection and aggregation into `run_eval.py`.
9. Update Eval documentation and execute the automatic verification guide.
10. Stop before the full live matrix and request explicit budget approval.

## Complexity Tracking

No constitution violations require justification.
