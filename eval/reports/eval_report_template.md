# FlashNovel Eval Report

## Metadata

| 字段 | 值 |
| --- | --- |
| Eval version | v1 |
| Date | YYYY-MM-DD |
| Dataset | `eval/datasets/flashnovel_eval_v1.jsonl` |
| Dataset scope | Generated from `summary.json.dataset_scope` |
| Execution scope | Generated from `summary.json.execution_scope` |
| Coverage status | `complete` or `partial`, with explicit reasons |
| Systems | `naive_recent_text`, `structured_memory_only`, `flashnovel_full` |
| Judge prompts | `continuity_judge_prompt.md`, `coverage_judge_prompt.md` |

## Executive Summary

本节必须从 `summary.json` 生成，明确区分完整数据集范围和本次执行范围。当前 v1
数据集应显示 20 cases、28 target chapters；每个系统的实际目标章节和生成章节须分别
核对。

只允许输出描述性比较。`partial` 结果、缺失 judge、缺失 usage 或 unavailable 指标不得
用于证明任何系统整体更优。

## Overall Results

由 `summary.json.by_system` 生成。每个值必须同时展示 status、observed/denominator、
source 和 reason，不得保留空白单元格。

## Hard Metrics

由 `summary.json.by_system.*.hard_metrics` 生成。dry-run 不进入 live 指标；checkpoint
只统计符合条件的多章节 full workflow case；memory write 使用 before/after 语义差异。

## Category Breakdown

由 `summary.json.by_tag` 生成，且系统之间不得混合样本数。

## Review And Rewrite Impact

`rewrite_improvement` 在没有可靠 before/after 标签时显示 `unavailable` 及原因。本模板
不得预设 rewrite 已降低冲突。

## Memory Quality

`memory_f1` 在没有经过验证的语义匹配算法时显示 `unavailable` 及原因。可展示
memory delta 写入证据，但不得将其等同于抽取质量。

## Notable Failures

| Case ID | System | Verdict | Failure Mode | Evidence |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Representative Examples

示例只能按明确的数据规则选择，并同时展示选择条件、样本范围和原始指标来源。不得使用
“最佳”“最大优势”等标题，除非完整矩阵和对应指标均为 complete。

## Cost And Latency

延迟来自逐请求计时。token 来自 provider usage，缺失时显示 `incomplete` 或
`unavailable`，不得填 0。成本在没有可追溯定价信息时显示 `unavailable`。

## Recommendations

建议必须引用本报告中的具体系统、指标、分母和状态。`partial` 报告不得给出基于整体优胜
假设的产品决策。

## Appendix

### Command

```powershell
python -m eval.run_eval --live --systems naive_recent_text,structured_memory_only,flashnovel_full
```

### Judge Configuration

- Judge model:
- Temperature:
- Retries:
- JSON repair policy:

### Raw Artifacts

- Run logs:
- Chapter artifacts:
- Judge outputs:
