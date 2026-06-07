# Output Contract

## CLI

Existing invocation remains compatible:

```powershell
python -m eval.run_eval `
  --dataset eval/datasets/flashnovel_eval_v1.jsonl `
  --systems naive_recent_text,structured_memory_only,flashnovel_full `
  [--limit N] [--case-id ID] [--live] [--no-judge] [--data-dir PATH]
```

Rules:

- no `--live` means dry-run and must make zero provider calls;
- `--live` requires configured credentials;
- full live execution is never invoked by tests or build scripts;
- duplicate and unknown systems are rejected;
- each invocation creates a new child directory and never reuses an existing directory.

## Run Directory

```text
eval/results/<timestamp>/
├── summary.json
├── eval_report.md
├── runs/<case_id>/<system>/
│   ├── prompt.md
│   ├── chapter.md
│   ├── completion.json        # baseline when available
│   ├── events.json            # full workflow when available
│   ├── memory_before.json     # full workflow
│   ├── memory_after.json      # full workflow
│   ├── memory_delta.json      # semantic before/after differences
│   └── error.json             # failure when applicable
└── judges/*.json
```

Files that cannot be produced due to an earlier failure are omitted and represented as
`unavailable` with a reason in `summary.json`.

## Report Sections

`eval_report.md` must contain, in order:

1. prominent coverage status (`COMPLETE` or `PARTIAL`) and reasons;
2. metadata with full dataset and execution scope;
3. evidence-bounded executive summary;
4. per-system hard metrics;
5. per-system soft metrics;
6. per-tag comparison;
7. LLM usage and latency completeness;
8. unavailable/incomplete metrics and reasons;
9. case-system results and failures;
10. reproducibility notes.

The report must not contain a prewritten winning system or unsupported improvement claim.

## Repository Boundary

- `eval/results/` remains ignored and is raw, local evidence.
- A sanitized formal summary may be intentionally copied to a tracked report path only after
  review; this feature does not automate that publication.
- Existing result directories and historical reports are never rewritten or deleted.
