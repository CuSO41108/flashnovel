# Quickstart: 可信评测指标与报告

## Prerequisites

- Run from repository root.
- Use a Python environment with project development dependencies.
- Do not configure or use an API key for automatic verification.
- Keep `eval/results/` ignored and do not modify existing result directories.

## 1. Focused Tests

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m pytest `
  backend/tests/test_eval_metrics.py `
  backend/tests/test_eval_report.py `
  backend/tests/test_eval_runner.py `
  backend/tests/test_runtime_recovery_and_budget.py -q
```

Expected:

- all selected tests pass;
- fake clients only;
- no provider requests.

## 2. Complete Backend Suite

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m pytest backend/tests -q
```

Expected: zero failures.

## 3. Dry-Run Smoke

Use a temporary output directory so repository evidence remains untouched:

```powershell
$smoke = Join-Path $env:TEMP "flashnovel-eval-smoke"
python -m eval.run_eval `
  --output-dir $smoke `
  --limit 1 `
  --systems naive_recent_text,structured_memory_only,flashnovel_full
```

Expected:

- mode is `dry-run`;
- live call count is zero;
- coverage is visibly `partial`;
- live-only metrics are `unavailable`, not 0 or 1;
- a new unique child directory is created.

## 4. Inspect Summary And Report

```powershell
$latest = Get-ChildItem -LiteralPath $smoke -Directory |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 1

Get-Content -LiteralPath (Join-Path $latest.FullName "summary.json")
Get-Content -LiteralPath (Join-Path $latest.FullName "eval_report.md")
```

Check:

- dataset scope reports 20 cases and 28 target chapters;
- execution scope reports one selected case and three systems;
- report contains per-system sections and a PARTIAL banner;
- unavailable metrics include reasons;
- no system is declared the winner.

## 5. Historical Result Guard

Before and after focused tests and dry-run:

```powershell
git status --short -- eval/results
```

Expected: no tracked historical result changes. New local raw output remains ignored.

## 6. Manual Full Live Gate

Do not execute this step during implementation or ordinary verification.

Required first:

1. Human explicitly approves API budget.
2. Provider, model and judge configuration are recorded.
3. The automatic checks above pass.

Only after approval:

```powershell
$env:FLASHNOVEL_API_KEY="<configured outside source control>"
$env:FLASHNOVEL_BASE_URL="<approved provider endpoint>"
$env:FLASHNOVEL_MODEL="<approved model>"

python -m eval.run_eval `
  --live `
  --systems naive_recent_text,structured_memory_only,flashnovel_full
```

Release review must confirm:

- 20 dataset cases and 28 target chapters;
- all 60 case-system combinations succeeded;
- required judge metrics are available;
- each actual LLM request has a call record;
- missing usage is marked rather than converted to zero;
- conclusions match measured per-system values.
