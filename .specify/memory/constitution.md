<!--
Sync Impact Report
- Version change: template (unratified) -> 1.0.0
- Added principles:
  - I. Evidence Before Claims
  - II. Trustworthy Metrics
  - III. Single Execution Path
  - IV. Explicit State Ownership
  - V. Incremental Refactoring
  - VI. Verification Gates
  - VII. Repository Safety
- Added sections:
  - Engineering Constraints
  - Development Workflow
  - Governance
- Templates updated:
  - ✅ .specify/templates/plan-template.md
  - ✅ .specify/templates/spec-template.md
  - ✅ .specify/templates/tasks-template.md
- Templates reviewed without changes:
  - ✅ .specify/templates/checklist-template.md
  - ✅ .specify/templates/constitution-template.md
- Command templates:
  - ✅ No .specify/templates/commands directory is present
- Runtime guidance reviewed:
  - ✅ AGENTS.md
  - ✅ README.md
- Deferred items: none
-->

# FlashNovel Constitution

## Core Principles

### I. Evidence Before Claims

All evaluation conclusions, README statements, and resume claims MUST be
supported by reproducible data. The scope of each conclusion MUST match the
scope of the experiment that produced it. Incomplete experiments MUST be
labelled `partial`; partial results MUST NOT be presented as complete findings
or as proof of an unverified improvement.

### II. Trustworthy Metrics

Every metric MUST state its sample scope and denominator, data source,
calculation method, applicable conditions, and known limitations. `dry-run`
results MUST NOT count toward live-run success rates. Memory-write metrics MUST
measure changes between pre-run and post-run state. Token usage, cost, and
latency MUST come from actual model calls rather than estimates of substitute
prompts.

### III. Single Execution Path

Each Tool category MUST have one official runtime implementation, one
registration entry point, and one behavioral test suite. A legacy
implementation MAY remain temporarily during migration, but it MUST NOT also
serve as an official execution path. The migration MUST document affected call
sites, compatibility boundaries, and objective removal criteria.

### IV. Explicit State Ownership

Run-state transitions MUST be owned by one component. `pause`, `cancel`,
`resume`, `confirm`, and `recovery` MUST have distinct, testable semantics.
Terminal states MUST NOT be overwritten by later workflow nodes. Illegal
transitions MUST be rejected and recorded with enough context for diagnosis.

### V. Incremental Refactoring

Large modules such as Store MUST be refactored through incremental extraction,
not a big-bang rewrite. Each step MUST address one explicit responsibility,
preserve externally observable behavior, and pass regression tests before the
next extraction begins. Every compatibility layer MUST have measurable removal
criteria.

### VI. Verification Gates

A behavioral change MUST begin with a test that reproduces the current problem
and fails for the expected reason. After implementation, contributors MUST run
directly related tests, the complete backend test suite, and any affected
frontend, Eval, or build checks. Performance or quality improvements MUST NOT
be claimed without complete experimental evidence.

### VII. Repository Safety

Secrets, real environment configuration, runtime databases, unsanitized user
data, and temporary or raw evaluation outputs MUST NOT be committed.
Sanitized, reproducible evaluation summaries and formal reports MAY be
committed. Batch deletion of files or directories is prohibited; every
deletion MUST target one explicit file path.

## Engineering Constraints

- Evaluation artifacts MUST distinguish source data, raw run output, derived
  metrics, and publishable summaries.
- Evaluation runs MUST record enough configuration and provenance to reproduce
  the reported result.
- Runtime-path, state-machine, and Store refactors MUST preserve public
  contracts unless the active feature specification explicitly approves a
  migration.
- Constitution exceptions MUST be documented in the implementation plan's
  Complexity Tracking table with a reason and a rejected simpler alternative.

## Development Workflow

1. Define independently testable behavior and measurable success criteria in
   the feature specification.
2. Complete the Constitution Check before research and repeat it after design.
3. Add a failing regression or behavior test before changing implementation.
4. Implement the smallest scoped change that satisfies the specification.
5. Run all required verification gates and record commands and outcomes.
6. Review generated reports and documentation so their claims match the
   evidence before committing.

## Governance

This constitution takes precedence over conflicting project practices and
generated feature artifacts. Amendments MUST include the motivation, affected
principles or sections, migration impact, and synchronized updates to dependent
templates.

Version changes follow semantic versioning:

- MAJOR for removal or incompatible redefinition of a governing principle.
- MINOR for a new principle or materially expanded mandatory guidance.
- PATCH for clarifications that do not change required behavior.

Every feature plan and code review MUST verify constitutional compliance.
Unresolved violations block implementation or merge unless explicitly
documented in Complexity Tracking and approved as part of the feature plan.

**Version**: 1.0.0 | **Ratified**: 2026-06-07 | **Last Amended**: 2026-06-07
