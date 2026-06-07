# Feature Specification: 可信评测指标与报告

**Feature Branch**: `001-trustworthy-eval-report`

**Created**: 2026-06-07

**Status**: Draft

**Input**: User description: "建立可信评测指标与报告功能，修复数据集规模、dry-run、
memory write、LLM usage、token budget、分系统报告、checkpoint、partial run 和验证门禁。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 获得口径可信的评测摘要 (Priority: P1)

作为项目维护者，我希望评测摘要准确区分数据集范围、实际执行范围和指标适用范围，
从而不会把 dry-run、seed memory 或不适用样本计入真实效果指标。

**Why this priority**: 当前统计会产生确定性的误导，包括错误的数据集章节数、
dry-run 成功率、memory write 和 checkpoint 分母。若这些基础口径不可信，其他比较结果
没有发布价值。

**Independent Test**: 使用包含单章、多章、dry-run、live、seed memory 和运行后 memory
变化的固定样例生成摘要；逐项手工计算分子和分母，并验证摘要结果完全一致。

**Acceptance Scenarios**:

1. **Given** 当前完整数据集包含 20 个 case，其中 18 个目标章节数为 1、2 个目标章节数为
   5，**When** 读取数据集元数据，**Then** 报告显示 20 cases 和 28 target chapters。
2. **Given** 一次运行只选择前 5 个 case，**When** 生成摘要，**Then** 报告同时显示完整
   数据集范围和本次执行范围，并将本次运行标记为 `partial`。
3. **Given** 一次 dry-run，**When** 生成指标，**Then** live-only 成功率和事件完整性不把
   dry-run 结果计入分子或分母，并显示为不适用或不可用。
4. **Given** 评测开始前已经注入 seed memory，且运行后没有新增或修改 memory，
   **When** 计算 memory write，**Then** 结果不是写入成功。
5. **Given** 只有明确要求 checkpoint 的多章节 case，**When** 计算 checkpoint rate，
   **Then** 分母只包含符合 checkpoint 条件且支持该行为的记录。

---

### User Story 2 - 按系统审查效果和运行成本 (Priority: P1)

作为评测结果审查者，我希望看到每个系统各自的 Coverage、Continuity、硬指标和调用
信息，从而能够比较系统差异，而不是被混合后的总体平均掩盖。

**Why this priority**: 三个系统的总体平均无法回答哪个系统更好，而且当前完整工作流的
token 使用缺失、上下文预算口径错误，无法评估其真实成本和约束表现。

**Independent Test**: 使用三个系统各自具有不同固定分数、调用数、上下文长度和错误状态
的样例生成报告；验证每个系统的聚合值、分母和不可用字段均可独立追溯到原始记录。

**Acceptance Scenarios**:

1. **Given** 三个系统均有结果，**When** 生成报告，**Then** 报告为每个系统分别展示
   Coverage、Continuity、contradiction 和适用的硬指标。
2. **Given** 完整工作流发生多次模型调用，**When** 汇总调用信息，**Then** 每次实际调用
   都有可追踪记录，至少包含阶段、模型、状态、延迟和错误信息；提供方返回 token usage
   时也必须记录 prompt、completion 和 total token。
3. **Given** 模型提供方没有返回某次调用的 token usage，**When** 生成报告，**Then**
   该数据标记为 `unavailable` 或 `incomplete`，不得以 0 代替。
4. **Given** 完整工作流由 Context Builder 装配上下文，**When** 计算 token budget
   是否通过，**Then** 使用实际装配并提交给后续生成流程的上下文，而不是替代性的评测
   描述 prompt。
5. **Given** 某指标不适用于一个系统，**When** 展示该系统结果，**Then** 报告显示
   `unavailable` 及原因，而不是将其作为 0 参与跨系统平均。

---

### User Story 3 - 防止不完整实验产生过度结论 (Priority: P1)

作为 README、报告或简历内容的撰写者，我希望报告明确指出实验是否完整、哪些指标尚不可用
以及允许得出哪些结论，从而不会把小样本或占位模板描述成已经证明的效果提升。

**Why this priority**: 当前只有 5 个 case 的三系统对比，且结果并未证明完整工作流在所有
指标上更好。结论边界必须和证据同步修复。

**Independent Test**: 分别生成 partial dry-run、partial live run、完整但未启用 judge 的
live run，以及覆盖全部数据集和系统的 live run；验证报告状态、警告和可发布结论随证据
范围正确变化。

**Acceptance Scenarios**:

1. **Given** 运行未覆盖完整数据集或所声明的全部比较系统，**When** 生成报告，
   **Then** 标题附近和 Executive Summary 中均明显显示 `partial`。
2. **Given** 一次 partial run，**When** 生成结论，**Then** 报告不得使用“证明更优”、
   “明显提升”或等价的整体性结论。
3. **Given** `memory_f1`、rewrite improvement、readability 或 cost 缺乏可靠数据，
   **When** 生成正式报告，**Then** 相应字段显示 `unavailable` 及原因，且 Executive
   Summary 不引用这些指标。
4. **Given** 完整工作流的 Continuity 低于任一 baseline，**When** 生成比较摘要，
   **Then** 报告如实展示差异，不自动生成完整工作流更优的预设结论。

---

### User Story 4 - 在预算确认后完成正式发布门槛 (Priority: P2)

作为负责模型费用的维护者，我希望完整 live 评测只能在人工确认预算后执行，并在完成后
生成可复现、可审查的正式摘要。

**Why this priority**: 完整 20-case 三系统评测会产生真实模型费用，不能作为普通自动化
测试隐式运行，但又必须成为发布效果结论前的明确门槛。

**Independent Test**: 在不提供人工预算确认时验证完整 live run 不会被验证流程自动触发；
在明确确认后执行完整矩阵，并核对运行清单、配置、结果覆盖和报告完整性。

**Acceptance Scenarios**:

1. **Given** 未获得人工预算确认，**When** 执行普通测试或构建检查，**Then** 不会自动
   发起完整 live 评测。
2. **Given** 已人工确认预算并执行正式评测，**When** 运行结束，**Then** 运行记录覆盖
   全部 20 个 case、28 个目标章节和所有声明参与比较的系统。
3. **Given** 正式评测有失败或缺失的 case-system 组合，或任一组合实际生成章节数少于
   `max_chapters`，**When** 生成报告，**Then** 报告列出缺失项、失败项和章节缺口，并
   保持 `partial`，直至完整矩阵成功且所有目标章节均已生成。

### Edge Cases

- 数据集为空、case 缺失 `max_chapters`、值为零、负数或非整数时，数据集规模不得静默
  生成误导性数值；无效 case 必须被拒绝或明确记录。
- `--limit` 大于数据集规模、选择零个系统、重复系统名或未知系统名时，运行范围和
  `partial` 状态必须保持确定且可解释。
- 一个 live run 中部分调用成功、部分调用失败时，调用次数、失败原因、延迟和可用 token
  信息必须保留，聚合值不得把失败调用当作零成本。
- 模型调用成功但 usage 缺失时，运行成功状态和 usage 完整性必须分别表达。
- memory 项内容发生更新但数量不变时，应视为变化；仅存在初始 seed memory 不算写入。
- 非 checkpoint case、非完整工作流系统和因更早失败而未到达 checkpoint 的记录，必须
  分别表达为不适用、不可用或失败，不能混为同一种 0。
- judge 被禁用、judge 失败或只返回部分指标时，软指标必须显示其覆盖率和不可用原因。
- 报告中没有数据的表格或字段不得保留空白以暗示结果将在之后自动成立。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 分别报告完整数据集范围和本次执行范围，包括 case 数量与
  `max_chapters` 汇总得到的目标章节数。
- **FR-002**: 对当前完整数据集，系统 MUST 报告 20 cases 和 28 target chapters。
- **FR-003**: 系统 MUST 根据实际覆盖的 case、系统、成功的 case-system 组合以及每个
  组合实际生成的目标章节判定 `coverage_status` 是 `complete` 还是 `partial`，并记录
  判定原因。judge、usage、成本等数据完整性 MUST 使用各自的 metric status 表达，不得
  改写 coverage status。
- **FR-004**: dry-run 结果 MUST 与 live 结果分开汇总；live-only 指标 MUST 排除
  dry-run 的分子和分母。
- **FR-005**: dry-run MUST 保留验证 prompt 和产物布局所需的独立状态，但不得被解释为
  运行成功、事件完整或模型效果得分。
- **FR-006**: 完整工作流的事件完整性 MUST 仅由实际观察到的必需工作流事件决定，
  不得存在无条件通过路径。
- **FR-007**: 每个 rate 指标 MUST 输出分子、分母、比率、适用条件和排除记录的原因；
  分母为零时 MUST 显示 `unavailable`，不得伪造为 0% 或 100%。
- **FR-008**: memory write MUST 比较运行前后状态，并在预期 memory 类别中识别新增或
  内容变化；预先注入的 seed memory MUST NOT 单独构成写入成功。
- **FR-009**: checkpoint rate 的分母 MUST 仅包含 case 明确要求达到 checkpoint 且
  被评系统支持该行为的记录。
- **FR-010**: token budget MUST 基于每个系统实际使用的输入；完整工作流 MUST 使用
  Context Builder 实际装配的上下文。
- **FR-011**: 系统 MUST 为每次实际模型调用记录调用阶段、模型标识、成功或失败状态、
  延迟和错误信息。
- **FR-012**: 当模型提供方返回 usage 时，系统 MUST 记录 prompt、completion 和 total
  token；usage 缺失时 MUST 标记缺失，不得记录为零。
- **FR-013**: 系统 MUST 报告调用记录覆盖率，使读者能够判断 token、成本和延迟聚合是否
  完整。
- **FR-014**: 报告 MUST 按系统分别聚合 Coverage、Continuity、contradiction 和所有
  适用硬指标，并展示各自样本数。
- **FR-015**: 报告 MUST 允许按评测标签查看各系统的样本数和可用软指标，以揭示样本构成
  差异。
- **FR-016**: 跨系统总体平均 MAY 作为补充信息存在，但 MUST NOT 替代按系统结果，也
  MUST NOT 被用作某一系统更优的证据。
- **FR-017**: 未可靠实现或数据不足的 `memory_f1`、rewrite improvement、readability、
  cost 和 latency 指标 MUST 显示 `unavailable` 或 `incomplete` 及具体原因。
- **FR-018**: 报告 MUST 从已计算数据生成描述性结论，不得包含预设的效果提升结论。
- **FR-019**: coverage partial 报告 MUST 在报告开头、Executive Summary 和机器可读
  摘要中明显标记，并列出缺少的 case、系统、失败组合或目标章节。judge、usage 或调用
  数据缺失 MUST 作为独立的 `incomplete`/`unavailable` 指标警告列出。
- **FR-020**: 系统 MUST 保存足够的运行配置和来源信息，以复现数据集选择、系统选择、
  live/dry-run 模式、judge 状态和报告聚合结果。
- **FR-021**: 系统 MUST 为指标计算、报告渲染、dry-run 隔离、partial 判定、调用数据
  缺失和已确认缺陷提供自动化回归测试。
- **FR-022**: 完整 live 评测 MUST 是人工预算确认后的显式操作，普通测试、构建和
  dry-run MUST NOT 隐式触发它。
- **FR-023**: 本 feature MUST NOT 统一 Tool 实现、重构 Run 状态所有权、拆分 Store
  或改变这些模块的公共架构；仅允许为准确采集模型调用信息所必需的局部埋点变更。

### Key Entities

- **Dataset Scope**: 完整数据集的身份、case 数量、目标章节数和可用标签。
- **Execution Scope**: 本次实际选择和尝试的 case、系统、目标章节、运行模式与 judge
  配置。
- **Case-System Result**: 一个 case 在一个系统下的状态、适用性、产物、事件、memory
  差异、预算信息和 judge 结果。
- **Metric Definition**: 指标名称、分子、分母、数据来源、适用条件、排除原因、结果值
  和已知局限。
- **LLM Call Record**: 一次真实模型调用的阶段、模型、状态、延迟、usage 可用性、token
  数据和错误信息。
- **Evaluation Summary**: 机器可读的完整性状态、范围、按系统聚合、按标签聚合和缺失
  数据清单。
- **Evaluation Report**: 面向审查者的可读报告，所有结论均可追溯到 Evaluation Summary。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 当前完整数据集在摘要和报告中均显示 20 cases、28 target chapters，
  与逐 case 汇总结果 100% 一致。
- **SC-002**: 在覆盖 dry-run、live、seed-only memory、memory 更新和 checkpoint
  适用性的固定测试矩阵中，所有 rate 指标的分子、分母和比率与独立手工计算 100% 一致。
- **SC-003**: dry-run 生成的任何记录都不会进入 live run success 或 live event
  completeness 的分子或分母。
- **SC-004**: 三个系统的 Coverage、Continuity 和适用硬指标均有独立行、独立样本数和
  独立适用性说明，不再只提供混合总体平均。
- **SC-005**: 完整工作流中 100% 的实际模型调用具有调用阶段、模型、状态和延迟记录；
  token usage 的可用或缺失状态对 100% 的调用均明确表达。
- **SC-006**: 所有不可计算指标均显示 `unavailable` 或 `incomplete` 及原因，正式报告中
  不存在无解释空白值、伪造的零值或基于该指标的结论。
- **SC-007**: 所有未覆盖完整声明矩阵的运行都在报告开头和摘要中标记 `partial`，且
  自动生成的结论不包含整体效果提升声明。
- **SC-008**: 已确认的 dry-run 恒真、seed memory 假阳性、错误 checkpoint 分母和实际
  上下文预算四类缺陷均有至少一个先失败后通过的回归测试。
- **SC-009**: 普通自动化验证产生 0 次付费 live 模型调用；完整 live 评测只有在人工
  确认预算后才执行。
- **SC-010**: 获得预算确认后的正式报告覆盖 20 个 case、每个系统各自应生成的 28 个
  目标章节和所有声明参与比较的系统；任何 case-system 失败、缺失或章节生成不足都会
  阻止 coverage status 被标记为 complete。

每个成功标准的样本范围、分母、来源和限制如下：

- SC-001 使用完整 `flashnovel_eval_v1` 数据集，以有效 case 为分母，不接受 partial。
- SC-002、SC-003、SC-005、SC-006 和 SC-008 使用确定性测试样例，不依赖付费模型调用。
- SC-004 和 SC-007 使用包含三个系统及不同覆盖范围的报告样例。
- SC-009 覆盖普通测试、构建和 dry-run 路径。
- SC-010 只适用于人工批准后的正式 live 发布门槛，不能由 partial 结果替代。

## Evidence & Verification *(mandatory)*

- **Required evidence**: 指标单元测试、报告快照或结构测试、已确认缺陷的回归测试、
  完整后端测试结果、无付费调用的 dry-run 结果，以及预算批准后完整 live 运行的机器
  可读摘要和脱敏正式报告。
- **Verification commands**: 计划阶段必须给出评测相关测试、完整后端测试、dry-run
  smoke、报告校验和人工批准 live run 的确切命令；live 命令必须与普通验证命令分开。
- **Claim boundaries**: 在完整 live 矩阵及所需 judge 数据完成前，README、报告和简历
  不得声称 FlashNovel full 明显优于 baseline、结构化记忆已提升效果、rewrite 已改善
  质量或成本已经可控。
- **Generated artifacts**: 数据集、rubric、确定性测试 fixture、脱敏汇总和正式报告可以
  提交；API key、真实环境文件、运行数据库、逐调用原始响应和临时 `eval/results`
  输出必须保持未跟踪。

## Assumptions

- 当前数据集中的 `run.max_chapters` 是目标章节数的权威来源；缺失值可按单章处理，但无效
  显式值必须报错。
- 当前 checkpoint 资格由 case 明确要求的多章节运行决定；普通单章 case 不进入分母。
- `memory_f1`、rewrite improvement 和 readability 本轮默认不新增未经验证的算法；若
  现有数据不足，则明确显示 `unavailable`。
- 延迟可以由每次真实调用直接观测；成本只有在模型定价信息明确且可追溯时才可计算，
  否则显示 `unavailable`。
- judge 可以被显式关闭；关闭后相关软指标不可用，且运行不能支持依赖这些指标的效果结论。
- API 预算批准由人工在运行前完成，本 feature 不建立计费审批系统。
- 现有数据集内容、三个系统定义和模型供应商选择保持不变，除非为修正错误元数据所必需。
