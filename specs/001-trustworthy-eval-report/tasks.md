# Tasks: 可信评测指标与报告

**Input**: Design documents from `/specs/001-trustworthy-eval-report/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/`, `quickstart.md`

**Tests**: 所有行为变更必须先写测试并确认测试因目标缺陷失败，再进行最小实现。自动化
任务只能使用 fake client 或 dry-run，不得发起付费模型调用。

**Organization**: 任务按用户故事组织。US1 是指标可信度 MVP；US2、US3 在其基础上增加
调用观测和报告边界；US4 的完整 live 运行是人工批准后的独立门禁。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可与同阶段标记任务并行，且不修改相同文件
- **[Story]**: 对应 `spec.md` 中的用户故事
- 所有路径均相对仓库根目录

## Phase 1: Setup

**Purpose**: 固化原始评测产物的仓库边界。

- [X] T001 确认并保留 `eval/results/` 忽略规则，仅修改 `.gitignore`，不得移动、覆盖或删除任何已有评测目录

---

## Phase 2: Foundational

**Purpose**: 建立所有用户故事共享的结构化 Eval 数据模型。

**CRITICAL**: 本阶段完成前不得实现任何指标或报告行为。

- [X] T002 在 `backend/tests/test_eval_metrics.py` 添加 `DatasetScope`、`ExecutionScope`、`MetricResult`、`MemoryDelta`、`ContextUsage` 和 `LLMCallRecord` 的序列化契约测试
- [X] T003 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认 `eval/models.py` 尚未实现导致新增契约测试失败
- [X] T004 在 `eval/models.py` 实现共享 dataclass、枚举值校验和递归 JSON 可序列化转换，字段与 `specs/001-trustworthy-eval-report/data-model.md` 一致
- [X] T005 重新运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认共享模型契约测试通过

**Checkpoint**: Eval 结果具备统一、可审计的数据表达。

---

## Phase 3: User Story 1 - 获得口径可信的评测摘要 (Priority: P1) MVP

**Goal**: 正确计算数据集范围、执行范围、指标分母、checkpoint 适用性和 memory write。

**Independent Test**: 固定样例能够得到 20 cases、28 target chapters；dry-run 不进入 live
指标；seed-only memory 不算写入；单章 case 不进入 checkpoint 分母。

### Tests for User Story 1

- [X] T006 [US1] 在 `backend/tests/test_eval_metrics.py` 添加完整数据集先于筛选加载、20/28 范围、重复 case id、缺失及非法 `max_chapters`、空/重复/未知 systems 和超大 `--limit` 的失败测试
- [X] T007 [US1] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认新增 DatasetScope 与 ExecutionScope 测试因当前筛选顺序和校验不足而失败
- [X] T008 [US1] 在 `eval/metrics.py` 实现完整数据集校验与 scope 构建，并在 `eval/run_eval.py` 中改为先加载全量数据再应用 `--case-id` 和 `--limit`
- [X] T009 [US1] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认数据集和执行范围测试通过
- [X] T010 [US1] 在 `backend/tests/test_eval_metrics.py` 添加 rate 分子/分母、零分母 unavailable、dry-run 排除、事件完整性和多章 checkpoint 资格的失败测试
- [X] T011 [US1] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认当前 bare-float 聚合、`dry_run` 成功状态和 nullable rate 行为导致测试失败
- [X] T012 [US1] 在 `eval/metrics.py` 实现结构化 `MetricResult` 聚合及 run success、artifact、event completeness、checkpoint 和 token budget 资格规则
- [X] T013 [US1] 在 `backend/tests/test_eval_metrics.py` 添加 seed-only、同数量内容更新、新增记录及忽略 ID/时间戳的 memory semantic delta 失败测试
- [X] T014 [US1] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认当前 final-memory-non-empty 判定导致新增 memory 测试失败
- [X] T015 [US1] 在 `eval/metrics.py` 实现 memory snapshot 规范化和五类 memory delta 计算
- [X] T016 [US1] 在 `backend/tests/test_eval_runner.py` 添加 dry-run 不伪造 event/checkpoint/memory、full workflow 保存 `memory_before.json` 与 `memory_after.json`、真实事件缺失即不完整、结果保存目标与实际章节数的失败测试
- [X] T017 [US1] 运行 `python -m pytest backend/tests/test_eval_runner.py -q`，确认 `_dry_run` 恒真字段和单快照实现导致新增 runner 测试失败
- [X] T018 [US1] 在 `eval/run_eval.py` 移除 dry-run 的伪成功字段，采集运行前后 memory 快照，并将事件和 memory delta 交给 `eval/metrics.py`
- [X] T019 [US1] 运行 `python -m pytest backend/tests/test_eval_metrics.py backend/tests/test_eval_runner.py -q`，确认 US1 全部测试通过且无真实 LLM 调用

**Checkpoint**: 此时可独立生成口径可信但仍较简化的机器可读摘要。

---

## Phase 4: User Story 2 - 按系统审查效果和运行成本 (Priority: P1)

**Goal**: 记录每次真实模型请求、实际 Context Builder 输入，并按系统和标签独立聚合。

**Independent Test**: 三个系统使用固定不同分数和调用数据时，报告前置摘要能逐系统追溯
Coverage、Continuity、硬指标、context budget、latency 和 usage 缺失状态。

### Tests for User Story 2

- [X] T020 [P] [US2] 在 `backend/tests/test_runtime_recovery_and_budget.py` 添加同步 Tool 正常 completion、usage 缺失、stream 成功和异常请求每次实际请求各产生一个 `llm.call` 记录的失败测试；stream 后 fallback 必须产生两条记录
- [X] T021 [US2] 运行 `python -m pytest backend/tests/test_runtime_recovery_and_budget.py -q`，确认当前仅少数 fallback 发出 `llm.usage` 导致新增调用观测测试失败
- [X] T022 [US2] 在 `backend/app/tools/sync_tools.py` 实现计时和异常安全的每请求 `llm.call` 观测，保留有 usage 时的兼容 `llm.usage` 事件且不改 Tool 注册入口
- [X] T023 [US2] 运行 `python -m pytest backend/tests/test_runtime_recovery_and_budget.py -q`，确认同步 Tool 调用观测测试和原有回退测试通过
- [X] T024 [P] [US2] 在 `backend/tests/test_eval_runner.py` 添加 baseline 与 judge call record 的模型、阶段、状态、延迟、usage complete/incomplete/unavailable 和错误记录失败测试
- [X] T025 [US2] 运行 `python -m pytest backend/tests/test_eval_runner.py -q`，确认当前 `EvalClient` 只返回 completion metadata 导致调用记录测试失败
- [X] T026 [US2] 在 `eval/run_eval.py` 为 `EvalClient` 增加逐请求计时与 `LLMCallRecord` 收集，并在 baseline、judge 和失败结果中保留调用记录
- [X] T027 [US2] 在 `backend/tests/test_eval_runner.py` 添加 full workflow 从 `kind="prompt"` artifact 读取实际 context、优先使用 `_context_budget.estimated_tokens`、缺失 artifact 时 unavailable 的失败测试
- [X] T028 [US2] 运行 `python -m pytest backend/tests/test_eval_runner.py -q`，确认当前 full workflow 使用评测描述 prompt 估算 token 导致 context budget 测试失败
- [X] T029 [US2] 在 `eval/run_eval.py` 读取本次 run 的 prompt artifacts，生成逐章 `ContextUsage`，并从 `llm.call` 事件构建完整工作流调用记录
- [X] T030 [US2] 在 `backend/tests/test_eval_metrics.py` 添加按系统及标签聚合 Coverage、Continuity、contradiction、硬指标样本数和 LLM usage 覆盖率的失败测试
- [X] T031 [US2] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认当前全系统混合平均和 usage 零值聚合导致测试失败
- [X] T032 [US2] 在 `eval/metrics.py` 实现 `by_system`、`by_tag`、软指标覆盖率、调用记录覆盖率、latency 和 token usage 完整性聚合
- [X] T033 [US2] 在 `backend/tests/test_eval_report.py` 添加每系统硬/软指标表、稳定系统排序、每标签比较、调用完整性、来源/分母和 unavailable 原因的失败报告测试
- [X] T034 [US2] 运行 `python -m pytest backend/tests/test_eval_report.py -q`，确认当前单一总体表和空白字段导致新增报告测试失败
- [X] T035 [US2] 在 `eval/reporting.py` 实现按系统、标签和调用完整性渲染，并在 `eval/run_eval.py` 中改用新报告模块
- [X] T036 [US2] 运行 `python -m pytest backend/tests/test_runtime_recovery_and_budget.py backend/tests/test_eval_metrics.py backend/tests/test_eval_runner.py backend/tests/test_eval_report.py -q`，确认 US2 全部测试通过

**Checkpoint**: 每个系统及每次 LLM 调用均可独立审查，缺失 usage 不再显示为零。

---

## Phase 5: User Story 3 - 防止不完整实验产生过度结论 (Priority: P1)

**Goal**: 明确 partial/complete 覆盖状态、不可用指标和允许结论范围。

**Independent Test**: partial dry-run、partial live、禁用 judge 和完整固定矩阵分别生成正确
状态；报告不含预设赢家或未验证提升。

### Tests for User Story 3

- [X] T037 [US3] 在 `backend/tests/test_eval_metrics.py` 添加 dry-run、缺 case、缺 system、失败组合、章节生成不足、禁用 judge 和完整 60 组合的 coverage status 与 reason 失败测试；禁用 judge 不得单独改变 coverage status
- [X] T038 [US3] 运行 `python -m pytest backend/tests/test_eval_metrics.py -q`，确认当前 summary 不区分 coverage 与 metric status 导致新增测试失败
- [X] T039 [US3] 在 `eval/metrics.py` 实现 coverage complete/partial 判定、确定性 reason 列表及 `memory_f1`、rewrite improvement、readability、cost 的 unavailable registry
- [X] T040 [US3] 在 `backend/tests/test_eval_report.py` 和 `backend/tests/test_eval_runner.py` 添加 PARTIAL banner、Executive Summary 结论边界、低于 baseline 如实展示、新目录不覆盖既有 sentinel 文件的失败测试
- [X] T041 [US3] 运行 `python -m pytest backend/tests/test_eval_report.py backend/tests/test_eval_runner.py -q`，确认当前报告预设结论和旧 summary 结构导致测试失败
- [X] T042 [US3] 在 `eval/reporting.py` 和 `eval/run_eval.py` 实现 summary schema v2、显著 partial 原因、描述性结论、不可用指标及 append-only 运行目录保护
- [X] T043 [US3] 更新 `eval/reports/eval_report_template.md`，删除 20×5=100 和预设 FlashNovel 优胜结论，改为数据驱动占位说明
- [X] T044 [US3] 运行 `python -m pytest backend/tests/test_eval_metrics.py backend/tests/test_eval_report.py backend/tests/test_eval_runner.py -q`，确认 US3 全部测试通过且历史 sentinel 未变化

**Checkpoint**: partial 结果无法被报告包装成完整实验或效果证明。

---

## Phase 6: User Story 4 - 在预算确认后完成正式发布门槛 (Priority: P2)

**Goal**: 自动验证保持零付费调用，并把完整 live 矩阵设为明确人工门禁。

**Independent Test**: 不配置 API key 时可完成全部自动测试和 dry-run；完整 live 命令不会被
测试或构建调用，并在人工批准前保持未执行。

### Verification And Documentation for User Story 4

- [X] T045 [US4] 在 `backend/tests/test_eval_runner.py` 增加 dry-run 不实例化 client factory、自动测试命令不需要 API key、live 缺凭据立即拒绝的回归测试
- [X] T046 [US4] 运行 `python -m pytest backend/tests/test_eval_runner.py -q`，确认自动路径产生 0 次真实模型调用
- [X] T047 [US4] 更新 `eval/README.md`，记录 20 cases/28 target chapters、自动 dry-run 验证、历史结果不可变规则和人工预算批准后的完整 live 命令
- [X] T048 [US4] 按 `specs/001-trustworthy-eval-report/quickstart.md` 完成所有无付费 preflight，并确认输出保持 `partial` 且 live call count 为 0（聚焦 48 passed；后端 66 passed；smoke 20/28、partial、0 calls）

**Checkpoint**: T048 完成表示代码可进入最终自动验证；完整 live 运行仍未获授权。

---

## Phase 7: Polish & Cross-Cutting Verification

**Purpose**: 执行宪章要求的最终证据与仓库安全检查。

- [X] T049 运行 `python -m pytest backend/tests/test_eval_metrics.py backend/tests/test_eval_report.py backend/tests/test_eval_runner.py backend/tests/test_runtime_recovery_and_budget.py -q` 并在 `specs/001-trustworthy-eval-report/tasks.md` 记录实际结果：52 passed in 1.59s
- [X] T050 运行 `$env:PYTHONPATH="$PWD\backend"; python -m pytest backend/tests -q` 并在 `specs/001-trustworthy-eval-report/tasks.md` 记录完整后端结果：70 passed, 8 existing FastAPI deprecation warnings in 1.79s
- [X] T051 运行 `npm test` 和 `npm run build` 于 `frontend/package.json` 所在目录，验证新增兼容事件不破坏前端事件展示：11 tests passed；Vite production build succeeded
- [X] T052 使用临时目录执行 `python -m eval.run_eval --limit 1 --systems naive_recent_text,structured_memory_only,flashnovel_full`，核对 `summary.json` 与 `eval_report.md` 满足 `specs/001-trustworthy-eval-report/contracts/output-contract.md`：临时输出契约校验通过
- [X] T053 使用 Python 解析 `specs/001-trustworthy-eval-report/contracts/eval-summary.schema.json` 和 dry-run `summary.json`，核对必需字段、枚举状态、20/28 dataset scope 与零 live calls：Draft 2020-12 schema validation passed
- [X] T054 运行 `git status --short`、`git diff --check` 和 `git status --short -- eval/results`，确认没有密钥、数据库、原始结果或历史评测修改被纳入提交：边界扫描通过，历史 `eval/results` 保持 ignored
- [X] T055 审查 `eval/README.md`、`eval/reports/eval_report_template.md` 和生成报告，确认无“明显提升”“证明更优”等超出证据的表述，且未修改 Tool 注册、Run 状态或 Store 架构：仅修改同步 Tool 调用埋点及 check 节点 run_id 传递，registry/state/store 未变

---

## Phase 8: Manual Full Live Release Gate

**Purpose**: 在代码和所有自动验证完成后，等待人工预算批准并生成正式发布证据。

- [ ] T056 [US4] 人工门禁：仅在用户明确批准 API 预算后，按 `specs/001-trustworthy-eval-report/quickstart.md` 执行完整 20-case/3-system live 评测，审查 60 个组合及各系统实际生成的 28 个目标章节；未批准时必须停止并保持本任务未完成

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: 无依赖。
- **Phase 2 Foundational**: 依赖 Phase 1，阻塞全部用户故事。
- **US1 (Phase 3)**: 依赖 Foundational，是 MVP 和后续聚合的基础。
- **US2 (Phase 4)**: 依赖共享模型；调用观测子任务 T020-T023 可与 US1 指标工作并行，
  但聚合和报告任务依赖 US1。
- **US3 (Phase 5)**: 依赖 US1 scope 和 US2 reporting。
- **US4 (Phase 6)**: 自动门禁依赖 US1-US3。
- **Phase 7**: T049-T055 在 T048 之后执行。
- **Phase 8**: T056 依赖 T049-T055 全部通过以及用户明确预算批准。

### User Story Dependencies

```text
Foundational
    |
    +--> US1 (MVP: trustworthy scope and metrics)
    |       |
    |       +--> US2 (per-system reporting and call observability)
    |               |
    |               +--> US3 (partial status and claim boundaries)
    |                       |
    |                       +--> US4 automatic preflight
    |                               |
    |                               +--> Final automatic verification
    |                                       |
    |                                       +--> T056 manual paid live gate
    |
    +--> T020-T023 sync Tool call observability may start in parallel with US1
```

### Within Each User Story

1. 写新增测试。
2. 单独运行并确认因目标缺陷失败。
3. 实现最小代码。
4. 重新运行该故事测试。
5. 通过 checkpoint 后再进入下一故事。

## Parallel Opportunities

### US1 And LLM Observation

在共享模型完成后，以下两条工作线可并行：

```text
Track A: T006-T019 in eval/metrics.py, eval/run_eval.py, backend/tests/test_eval_metrics.py
Track B: T020-T023 in backend/app/tools/sync_tools.py,
         backend/tests/test_runtime_recovery_and_budget.py
```

### US2 Test Preparation

T024 的 EvalClient 调用测试与 T020 的同步 Tool 调用测试修改不同文件，可并行编写；各自
失败验证完成后，再按 T026 和 T022 实现。

## Implementation Strategy

### MVP First

1. 完成 T001-T005。
2. 完成 T006-T019。
3. 停止并验证 US1：20/28、dry-run 隔离、checkpoint 分母和 memory delta。

此时已有可独立交付的可信硬指标基础，但尚不能发布完整系统效果比较。

### Incremental Delivery

1. **US1**: 修正数据范围和硬指标。
2. **US2**: 增加逐系统结果、真实 context 和每次 LLM 调用观测。
3. **US3**: 增加 partial 警示、不可用指标和结论边界。
4. **US4**: 完成零付费 preflight，等待预算批准后才运行完整矩阵。
5. **Final**: 完整测试、构建、仓库安全和表述审查。

## Requirement Coverage

| Requirements | Tasks |
| --- | --- |
| FR-001–FR-003 | T006-T009, T037-T039 |
| FR-004–FR-007 | T010-T012, T016-T019 |
| FR-008 | T013-T018 |
| FR-009 | T010-T012 |
| FR-010 | T027-T029 |
| FR-011–FR-013 | T020-T032 |
| FR-014–FR-016 | T030-T036 |
| FR-017–FR-019 | T037-T044 |
| FR-020 | T008, T026, T029, T042 |
| FR-021 | T002-T055 |
| FR-022 | T045-T048, T056 |
| FR-023 | T022, T029, T055 |

## Notes

- `[P]` 仅表示文件和直接依赖允许并行，不表示可以跳过失败测试验证。
- 不使用 `git add .`；提交前按路径审查和暂存。
- 不删除或重写 `eval/results/` 中任何历史目录。
- T056 是付费人工门禁，`/speckit-implement` 到达该任务时必须请求用户明确批准。
- `memory_f1`、rewrite improvement、readability 和 cost 本轮允许保持 `unavailable`，
  不得为了填表临时发明算法。
