# Research: 可信评测指标与报告

## Decision 1: Separate Coverage Completeness From Metric Availability

**Decision**: Represent run coverage as `complete` or `partial`, and represent every metric as
`complete`, `incomplete`, or `unavailable`.

**Rationale**: A provider may omit token usage while still returning valid chapter and judge
outputs. Treating every missing optional datum as a failed experiment would hide valid evidence;
treating it as zero would fabricate evidence. Separate statuses preserve both facts.

**Alternatives considered**:

- One global partial flag for any missing datum: rejected because provider usage can be absent
  indefinitely and is unrelated to Coverage/Continuity validity.
- Coverage-only status with free-text warnings: rejected because machines and tests could not
  reliably enforce metric-specific claim boundaries.

## Decision 2: Load Full Dataset Before Selection

**Decision**: Validate all dataset rows and compute full scope before applying `--limit` or
`--case-id`.

**Rationale**: A selected five-case run must still know that the source dataset contains 20 cases
and 28 target chapters. Computing scope after filtering makes partial detection impossible.

**Alternatives considered**:

- Infer full scope from README metadata: rejected because documentation can drift.
- Hard-code 20 and 28: rejected because future dataset changes would silently invalidate reports.

## Decision 3: Use Structured Metric Results

**Decision**: Return a structured result containing value, numerator, denominator, status, source,
applicability, exclusions, limitations and reason.

**Rationale**: Bare floats conceal denominator errors and turn “not applicable” into false zeroes.
The structure makes reports testable and allows downstream users to audit every value.

**Alternatives considered**:

- Float plus separate notes map: rejected because notes can become detached from the metric.
- Null-only unavailable values: rejected because null cannot distinguish no eligible samples from
  partial observations or unimplemented metrics.

## Decision 4: Derive Memory Writes From Semantic Snapshots

**Decision**: Snapshot memory after seed injection and after execution, then compare semantic
fields for summaries, timeline, relationships, foreshadows and state changes.

**Rationale**: Final non-empty state is guaranteed by seed injection in many cases. Comparing
semantic records detects both additions and same-count updates while ignoring generated IDs and
timestamps.

**Alternatives considered**:

- Count rows before and after: rejected because updates can occur without count changes.
- Filter only by `metadata.source`: rejected because generated records do not have one universal
  source marker and future producers could omit it.
- Modify Store to expose a new audit API: rejected as outside this feature's Store scope.

## Decision 5: Read Actual Context From Existing Prompt Artifacts

**Decision**: Use the `plan_chapter` prompt artifact's `context` field as the full-workflow input
for token-budget evaluation.

**Rationale**: The artifact already captures the Context Builder output passed through the active
runtime path. Reading it avoids adding Eval-specific state APIs or modifying Graph state ownership.

**Alternatives considered**:

- Continue measuring the Eval description prompt: rejected because it is not runtime context.
- Rebuild context after execution: rejected because memory has changed and would not reproduce the
  input used for generation.
- Add Context Builder state persistence to Store: rejected as unnecessary architectural expansion.

## Decision 6: Add Compatible Per-Request LLM Call Events

**Decision**: Emit `llm.call` exactly once for each actual request in the official sync Tool path,
and retain `llm.usage` when usage exists.

**Rationale**: Counting `tool.called` undercounts fallback requests and provides no latency,
failure, model or usage-completeness data. A new event avoids changing existing UI behavior while
making every request observable.

**Alternatives considered**:

- Instrument the HTTP client globally: rejected because it lacks run/tool identity and broadens
  production impact.
- Replace `llm.usage`: rejected because the frontend currently renders that event.
- Wrap RuntimeHost with an Eval-only client: rejected because RuntimeHost creates the client
  internally and the wrapper would miss non-Eval observability.

## Decision 7: Preserve Historical Outputs By Append-Only Run Directories

**Decision**: Every execution creates a new timestamped directory; implementation and tests never
rewrite existing result directories.

**Rationale**: Historical reports are evidence. Re-rendering them with new definitions would make
old and new results indistinguishable.

**Alternatives considered**:

- Migrate old summaries to the new schema: rejected because migration would imply facts that were
  not captured at run time.
- Delete obsolete runs: rejected by repository policy and evidence-preservation requirements.

## Decision 8: Keep Full Live Evaluation Outside Automated Verification

**Decision**: Unit, integration and dry-run checks must use fakes or no-LLM paths. The 20-case,
three-system live matrix is a documented manual gate requiring explicit budget approval.

**Rationale**: The matrix incurs external cost and may be slow or provider-dependent. It is
necessary for publishable effect claims, but inappropriate for ordinary CI or implementation
verification.

**Alternatives considered**:

- Run a small live smoke automatically: rejected because it still spends money and cannot prove
  the full claim.
- Skip live validation entirely: rejected because no effect conclusion would become publishable.
