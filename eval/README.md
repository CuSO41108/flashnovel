# FlashNovel Eval v1

本目录用于评估 FlashNovel 在长篇连续创作中的上下文选择、结构化记忆利用、连续性维护、多目标覆盖和 review/rewrite 改稿收益。

当前 `flashnovel_eval_v1.jsonl` 包含 20 cases：18 个单章 case、2 个五章 case，
合计 28 target chapters。该范围由每个 case 的 `run.max_chapters` 汇总得到，不能用
固定章节数乘以 case 数估算。

## Directory Layout

```text
eval/
  datasets/
    flashnovel_eval_v1.jsonl
  baselines/
    recent_text_prompt.md
    structured_memory_prompt.md
  rubrics/
    continuity_judge_prompt.md
    coverage_judge_prompt.md
  reports/
    eval_report_template.md
```

## Test Categories

| 类型 | 目标 | 典型失败 | 示例 |
| --- | --- | --- | --- |
| `continuity` | 检查设定、时间线、人物状态是否漂移 | 上章角色受伤，这章突然正常行动 | 第5章母亲住院，第6章不能完全康复 |
| `multi_instruction` | 检查用户多目标 prompt 是否被同时满足 | 只写悬念，遗漏规则解释或关系变化 | 同时强化互疑、解释规则、保留住院状态 |
| `foreshadow` | 检查伏笔是否延续、升级或正确回收 | 过早揭示核心谜底，或完全忽略伏笔 | 交易代价继续 open，但新增更具体线索 |
| `rule_consistency` | 检查世界规则是否被遵守 | 把有代价规则写成无代价能力 | 倒计时交易必须付出重要代价 |
| `character_state` | 检查人物伤病、心理、秘密、能力状态 | 人物立场突变且没有桥段支撑 | 小黑不能无条件信任杰瑞 |
| `relationship` | 检查关系变化是否与历史一致 | 敌对关系突然变成亲密同盟 | 合作关系自然滑向互相猜疑 |
| `timeline_repair` | 检查模型能否自然修补轻微时间线冲突 | 直接忽略冲突，或用旁白硬解释 | 发现冲突后在本章行动中补齐理由 |
| `budget_pressure` | 检查长历史下 context budget 的取舍 | 塞入低优先级历史，漏掉 canon/伏笔 | 小预算仍保留世界规则、关键人物状态 |
| `checkpoint_resume` | 检查多章生成的 checkpoint 与恢复 | 5章批次没有 awaiting_confirmation | 连续生成5章后产生 checkpoint |
| `memory_extraction` | 检查生成后是否写入可复用记忆 | 章节有关系变化但未写入 memory | relationship、foreshadow、state_change 被抽取 |

## Systems Under Test

| 名称 | 上下文 | 编排 | 用途 |
| --- | --- | --- | --- |
| `naive_recent_text` | 故事 premise + 最近 1-2 章正文或摘要 + 用户 prompt | 单次 draft | 最近正文 baseline |
| `structured_memory_only` | premise + characters/world_rules/timeline/relationships/foreshadows/state_changes/review_issues + 用户 prompt | 单次 draft | 验证结构化记忆本身的价值 |
| `flashnovel_full` | Context Builder 产出的高优先级上下文包 | `context -> plan -> draft -> extract -> check -> review -> rewrite -> commit` | 完整系统 |

## Dataset Schema

每行是一个 case：

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定 case id |
| `difficulty` | `easy` / `medium` / `hard` |
| `tags` | 评测分类标签 |
| `story` | 标题、前提、类型 |
| `seed_memory` | 评测前注入的结构化记忆 |
| `recent_context` | 给 naive baseline 使用的最近正文或摘要 |
| `run` | 起始章节、章节数、context budget、用户 prompt |
| `oracle` | must_cover、must_not 和 expected_memory_changes |

## Hard Metrics

不依赖 LLM judge，直接从运行记录、事件流、artifact 和 memory store 计算：

| 指标 | 定义 |
| --- | --- |
| `run_success_rate` | live 结果成功完成或进入 `awaiting_confirmation` 的比例；排除 dry-run |
| `artifact_exists_rate` | live 结果是否生成 chapter artifact |
| `event_complete_rate` | full workflow 的实际事件是否包含 `context/plan/draft/extract/check/review/commit` |
| `checkpoint_rate` | 明确要求 checkpoint 的多章 full workflow case 是否产生 checkpoint |
| `token_budget_pass_rate` | baseline 实际 prompt 或 full workflow 实际 Context Builder 输入是否在预算内 |
| `memory_write_rate` | full workflow 运行前后语义 memory 是否新增或变化；seed presence 不算写入 |

所有 rate 都输出 status、numerator、denominator、observed count、source 和适用条件。
零分母显示 `unavailable`，不得显示伪造的 0% 或 100%。

## Soft Metrics

使用 `rubrics/` 中的 LLM judge prompt 或人工评审：

| 指标 | 定义 |
| --- | --- |
| `coverage_score` | `must_cover` 命中数量 / `must_cover` 总数 |
| `contradiction_count` | 违反 `must_not` 的数量 |
| `continuity_score` | `1 - normalized(连续性冲突数)` |
| `memory_f1` | 当前未实现可靠语义匹配，正式输出为 `unavailable` |
| `rewrite_improvement` | 当前没有可靠 before/after 标签，正式输出为 `unavailable` |
| `readability_score` | 当前没有验证后的 rubric 数据，正式输出为 `unavailable` |

## Eval Matrix

正式矩阵覆盖当前数据集的 20 cases、每个系统各自的 28 target chapters 和三个系统：

```text
naive_recent_text
structured_memory_only
flashnovel_full
```

完整矩阵共有 60 个 case-system 组合。只有各组合成功且实际生成章节达到该 case 的
`max_chapters` 时，coverage status 才能是 `complete`。judge 或 usage 缺失使用独立
metric status 表达，不得伪装为零。

## Runner

runner 位于 `eval/run_eval.py`。默认是 dry-run，只渲染 prompt、写占位章节和汇总文件，
不实例化 LLM client，也不调用真实模型。dry-run 永远标记为 `partial`，且不进入 live
成功率、事件完整性、checkpoint 或 memory write 分母。

```powershell
python -m eval.run_eval --limit 1 --systems naive_recent_text,structured_memory_only
```

单 case live 调试必须显式传 `--live`，会使用项目 `.env` 或当前环境中的
OpenAI-compatible 配置调用模型：

```powershell
$env:FLASHNOVEL_BASE_URL="https://api.deepseek.com"
$env:FLASHNOVEL_MODEL="deepseek-chat"
$env:FLASHNOVEL_API_KEY="<your key, configured outside source control>"

python -m eval.run_eval --live --limit 1 --systems naive_recent_text,structured_memory_only
```

如果只配置了 `DEEPSEEK_API_KEY`，runner 会在 live 模式下默认使用：

```powershell
$env:DEEPSEEK_API_KEY="<your key, configured outside source control>"
python -m eval.run_eval --live --limit 1 --systems naive_recent_text
```

运行完整系统时，`flashnovel_full` 会复用后端 runtime 同步执行：

```powershell
python -m eval.run_eval --live --limit 1 --systems flashnovel_full
```

默认 live 模式会同时调用 continuity 和 coverage judge。若只想生成章节、不做 LLM 评审：

```powershell
python -m eval.run_eval --live --no-judge --limit 1 --systems naive_recent_text
```

输出目录默认为 `eval/results/<timestamp>/`：

```text
summary.json
eval_report.md
runs/<case_id>/<system>/prompt.md
runs/<case_id>/<system>/chapter.md
full workflow memory_before.json
full workflow memory_after.json
full workflow memory_delta.json
judges/*.json
```

每次运行创建新的唯一子目录。不得覆盖、修改或重新解释历史结果；`eval/results/`
保持在 `.gitignore` 中。

## Automatic Verification

普通测试和 smoke 验证不得配置或使用 API key：

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m pytest `
  backend/tests/test_eval_metrics.py `
  backend/tests/test_eval_report.py `
  backend/tests/test_eval_runner.py `
  backend/tests/test_runtime_recovery_and_budget.py -q

$smoke = Join-Path $env:TEMP "flashnovel-eval-smoke"
python -m eval.run_eval `
  --output-dir $smoke `
  --limit 1 `
  --systems naive_recent_text,structured_memory_only,flashnovel_full
```

smoke 输出必须显示完整 dataset scope 为 20/28、本次 execution scope 为 1 case/3
systems、coverage 为 `partial`、provider call count 为 0。

## Manual Live Release Gate

完整 live 矩阵会产生真实 API 费用，普通测试和构建不得隐式执行。只有维护者明确批准
API 预算，并记录 provider、model 与 judge 配置后，才能运行：

```powershell
python -m eval.run_eval `
  --live `
  --systems naive_recent_text,structured_memory_only,flashnovel_full
```

发布审查必须核对 60 个 case-system 组合、每个系统各自的 28 个目标章节、逐请求调用
记录、usage 缺失状态和按系统 judge 结果。在此之前，README、报告和简历不得声称任何
系统在整体效果上优于其他系统。
