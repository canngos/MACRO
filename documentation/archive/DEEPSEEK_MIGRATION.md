# Run the MACRO experiment with DeepSeek

Historical development record. Commands and status statements below describe that earlier stage. Use the [current run guide](../RUNNING.md) for execution.

This manual is for **Windows PowerShell** on this computer. Open a PowerShell terminal in Windows Terminal, VS Code, or PyCharm. Copy each command block in order, without copying the surrounding triple backticks. Keep the same terminal open so its variables remain available. If any command fails, stop and resolve the error before continuing.

The experiment compares a single judge with a panel of three specialists. Start with **one development case**, inspect its report, and then run **all 120 development cases**. Each case is evaluated twice with the candidates in opposite orders. The separate 400-case final evaluation comes after development and experiment freeze.

**Only commands containing `macro run` send requests to DeepSeek and spend API credits.** Planning, dataset checks, offline tests, and rebuilding reports do not call DeepSeek.

## 1. Open the project and select Python

Paste this entire block into PowerShell. It selects an existing Python environment on this computer; activation is unnecessary.

```powershell
Set-Location -LiteralPath 'C:\Users\shane\Documents\NLP\group_project\MACRO'
$ErrorActionPreference = 'Stop'

$pythonCandidates = @('.\.venv\Scripts\python.exe', '..\venv\Scripts\python.exe', '.\venv\Scripts\python.exe')
$taskPython = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $taskPython = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $taskPython) {
    throw 'No project Python environment found. Follow the fresh-install instructions at the end of this manual.'
}

& $taskPython --version
& $taskPython -m macro --help
if ($LASTEXITCODE -ne 0) { throw 'MACRO could not start. See Troubleshooting below.' }
```

The help output should list `audit`, `generate`, `validate`, `run`, `plan`, and `summarize`.

If you close the terminal, run this section again before using the other commands. On another computer, replace the path in `Set-Location` with the location of your `MACRO` project folder.

## 2. Add your DeepSeek API key

You need a DeepSeek API account, an API key, and sufficient API credits. A chat subscription is not a substitute for API access.

Open your existing local settings file, creating it from the example only if it does not exist:

```powershell
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad.exe .env
```

In Notepad, add the following line. Replace `PASTE_YOUR_REAL_KEY_HERE` with your actual API key. If `DEEPSEEK_API_KEY` already exists, edit that line instead of adding a duplicate. Save the file with **Ctrl+S**, then close Notepad.

```dotenv
DEEPSEEK_API_KEY=PASTE_YOUR_REAL_KEY_HERE
```

Keep the other settings in `.env`. The commands in this manual explicitly select the DeepSeek configuration, so an existing Ollama or DeepInfra provider setting will not replace DeepSeek.

Verify that the application can find a key without printing it:

```powershell
& $taskPython -c "from macro.shared.config import api_key; api_key({'provider': 'deepseek'}); print('DeepSeek key found. The key was not printed.')"
if ($LASTEXITCODE -ne 0) { throw 'Add DEEPSEEK_API_KEY to .env, save it, and try again.' }
```

This verifies that a nonempty key is present. The live smoke check below verifies whether DeepSeek accepts it. Keep `.env` private; it should not be committed or included in shared reports.

## 3. Select the configuration and verify the dataset

Use the thinking-disabled configuration for the development rerun. Its filename is historical: it now runs the current benchmark, not the old 20-case pilot.

```powershell
$deepseekConfig = 'configs/deepseek-pilot.json'
Get-Content -LiteralPath $deepseekConfig

& $taskPython -m macro validate --cases data/benchmark-v2/dev
if ($LASTEXITCODE -ne 0) { throw 'Dataset verification failed. Do not start a paid run.' }

& $taskPython -m macro plan --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 120
if ($LASTEXITCODE -ne 0) { throw 'Development planning failed. Do not start a paid run.' }
```

Check that the plan shows:

| Field | Expected value |
|---|---|
| `provider` | `deepseek` |
| `model` | `deepseek-flash` |
| Dataset `split` | `dev` |
| `cases` | `120` |
| `total_initial_calls` | `960` |
| `maximum_with_all_retries_and_tool_rounds` | `5760` |

The current configuration disables thinking, allows 3,500 output tokens per response, uses a 120-second timeout, allows two attempts per role, and allows two calculator rounds. A case has four initial judge requests in each of two candidate orders: eight initial requests in total. Retries and calculator follow-ups can add requests.

`--max-calls` limits requests, **not money**. The examples below permit the configured theoretical maximum; they do not predict how many requests will be used. Both DeepSeek configurations now include the Flash rate card below. Reports show estimates for recorded usage; they do not establish the actual amount billed.

### Configured DeepSeek Flash pricing

The rates below are in **USD per one million tokens**, from [DeepSeek's official pricing page](https://api-docs.deepseek.com/quick_start/pricing/), checked on 20 October 2026 for `DeepSeek-V4.1-Flash-1017` (`deepseek-flash`). Both thinking and non-thinking configurations use these rates.

| Token type | Off-peak | Peak |
|---|---:|---:|
| Input: cache hit | $0.003 | $0.006 |
| Input: cache miss | $0.15 | $0.30 |
| Output | $0.60 | $1.20 |

Peak hours are 01:00?04:00 and 06:00?10:00 UTC, Monday through Friday, excluding Chinese public holidays. All other times are off-peak.

`summary.json`, the Markdown report, and the HTML report show a **known-usage cost range** and a conservative **peak estimate**, including per-system estimates. Reported cache hits receive the cache-hit rate. If cache metadata is absent or inconsistent, the peak estimate treats those input tokens as misses; the lower bound allows them to be hits. These bounds cover recorded usage only: requests without usage can have additional unknown cost.

The reports do not automatically decide the billing tier from timestamps or guess Chinese public holidays. The lower bound uses off-peak rates; the upper bound uses peak rates. Your DeepSeek account's billing records establish the actual charge.

AutoGen supports only one input/output price pair. It is configured with **$0.0003 per 1,000 input tokens** and **$0.0012 per 1,000 output tokens**, using peak uncached rates to avoid its unknown-model pricing warning. Use the generated reports for cache-aware estimates.

The calculator is a local arithmetic tool; this experiment does not call the standalone Search or Fetch APIs. Their per-request charges are therefore not included.

Use fresh run IDs after this pricing/code change. Older runs retain their saved configuration, including `pricing: null`; rebuilding their reports does not silently add today's rates or change their manifests.

Do not regenerate or edit `data/benchmark-v2` when rerunning the experiment. The existing dataset is verified by the command above.

### Optional: rerun the offline software tests

The repaired implementation passed 91 offline tests. You can repeat them after pulling changes or if you want to check your installation. These tests do not call DeepSeek. Some use synthetic responses on the test split; these are software checks, not final model evaluation.

```powershell
& $taskPython -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Offline tests failed. Fix them before continuing.' }
```

The final output should say `OK`. Warnings about mock model prices or Python deprecations may appear during these checks.

## 4. Run one live development case

**This step spends DeepSeek API credits.** It runs both systems in both candidate orders: eight initial requests, with a cap of 48 requests including retries and calculator rounds.

Paste this block once. It creates a new run ID and remembers it in `tmp` so you can find it after closing the terminal.

```powershell
New-Item -ItemType Directory -Path 'tmp' -Force | Out-Null
$smokeRunId = 'deepseek-dev-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
Set-Content -LiteralPath 'tmp/last-deepseek-smoke-run.txt' -Value $smokeRunId

& $taskPython -m macro plan --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 1
if ($LASTEXITCODE -ne 0) { throw 'Smoke planning failed.' }

& $taskPython -m macro run --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 1 --allow-paid-api --max-calls 48 --run-id $smokeRunId
if ($LASTEXITCODE -ne 0) { throw 'Smoke run failed. Inspect its saved results before retrying.' }

& $taskPython -m macro summarize "results/$smokeRunId"
if ($LASTEXITCODE -ne 0) { throw 'Smoke report generation failed.' }

Start-Process -FilePath (Resolve-Path -LiteralPath "results/$smokeRunId/report.html").Path
```

The final command opens the HTML report in your browser. A successful terminal exit does not guarantee that every model assessment succeeded: the runner can save technical failures and still finish.

Before continuing, check the report for:

- Two completed evaluations per system: original and reversed candidate order.
- Provider `deepseek` and model `deepseek-flash`.
- No final `technical_failure` or missing evaluations.
- Valid JSON assessments, evidence links, recorded usage, and sensible decisions.
- Raw decisions and any changes made by the shared constraint guardrail.

A valid but incorrect judgment is still a model error that needs review. One successful case checks connectivity and basic output handling; it does not establish performance across all categories.

## 5. Run all 120 development cases

Continue after reviewing the smoke report. **This step spends API credits.** It starts a separate complete development experiment; it does not append to the smoke run or overwrite your earlier 120-case results.

```powershell
$devRunId = 'deepseek-dev-120-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
Set-Content -LiteralPath 'tmp/last-deepseek-dev-run.txt' -Value $devRunId

& $taskPython -m macro run --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 120 --allow-paid-api --max-calls 5760 --run-id $devRunId
if ($LASTEXITCODE -ne 0) { throw 'Development run failed. Inspect saved results before retrying.' }

& $taskPython -m macro summarize "results/$devRunId"
if ($LASTEXITCODE -ne 0) { throw 'Development report generation failed.' }

Start-Process -FilePath (Resolve-Path -LiteralPath "results/$devRunId/report.html").Path
```

Keep the terminal open while the run executes. Requests run sequentially. You can follow progress in the terminal; the final output identifies the results folder.

## 6. Read the development results

For a complete 120-case run, expect **240 completed evaluations per system** and **120 complete candidate-order pairs per system**. There are 48 planned observations per category: constraints, dominance, trade-offs, ties, and both candidates violating constraints.

The 240 observations repeat the same 120 cases in two orders; they are not 240 independent cases.

| File or folder inside `results/<run-id>/` | What to use it for |
|---|---|
| `report.html` | Read decisions, rationales, evidence, failures, and raw responses in a browser. |
| `report.md` | Read a short text summary. |
| `summary.json` | Inspect detailed metrics, raw metrics, guardrail changes, usage, and costs by system. |
| `roles/` | Inspect each judge's attempts, validation errors, and repairs. |
| `calls/` | Inspect recorded API responses, usage, and connection errors. |
| `manifest.json` | Check the exact configuration and experiment identity. |
| Case and private reference snapshots | Preserve the inputs used for that run. Keep private references separate from model input. |

Pay particular attention to tie cases, hard-constraint mistakes, malformed explanation responses, order disagreements, and differences between raw and guarded decisions. A correct final decision can still contain an incorrect score or violation finding.

The newer schema records positive `duration_minutes`, and the coordinator applies shared constraint checks. Preserve the old `deepseek-benchmark-dev-120-001` run as historical evidence; its scores describe the earlier implementation. See [the earlier findings](DEEPSEEK_DEV_120_REVIEW.md) and [the merge repair review](MERGE_REPAIR_REVIEW.md).

To reopen the latest development report in a new terminal, run section 1 first, then:

```powershell
$devRunId = (Get-Content -LiteralPath 'tmp/last-deepseek-dev-run.txt' -Raw).Trim()
& $taskPython -m macro summarize "results/$devRunId"
if ($LASTEXITCODE -ne 0) { throw 'Report generation failed.' }
Start-Process -FilePath (Resolve-Path -LiteralPath "results/$devRunId/report.html").Path
```

Rebuilding reports makes no model requests and does not rerun assessments.

## 7. Resume an interrupted development run

Resume only when the code, configuration, dataset, and Python environment are unchanged. Do not run two processes with the same run ID. A resume reuses successful saved role assessments and may make additional paid requests for unfinished work. It does not automatically give exhausted failures extra attempts.

To resume the latest full development run, run section 1 if needed, then paste:

```powershell
$deepseekConfig = 'configs/deepseek-pilot.json'
$devRunId = (Get-Content -LiteralPath 'tmp/last-deepseek-dev-run.txt' -Raw).Trim()

& $taskPython -m macro run --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 120 --allow-paid-api --max-calls 5760 --run-id $devRunId
if ($LASTEXITCODE -ne 0) { throw 'Resume failed. Read the error before trying again.' }

& $taskPython -m macro summarize "results/$devRunId"
if ($LASTEXITCODE -ne 0) { throw 'Report generation failed.' }
Start-Process -FilePath (Resolve-Path -LiteralPath "results/$devRunId/report.html").Path
```

If the runner reports changed code, configuration, prompts, schemas, or inputs, start a new experiment using section 5. Keep the previous results.

If the runner reports interrupted requests with uncertain completion or billing, inspect the saved files in `calls/`. Only after deciding to accept potentially repeating a billed request, add `--retry-uncertain` to the same `macro run` command. That flag permits repetition; it does not prove that the previous request was unbilled.

To resume the smoke check instead, use this command block. Do not execute the ID-creation lines in section 4 again when resuming.

```powershell
$deepseekConfig = 'configs/deepseek-pilot.json'
$smokeRunId = (Get-Content -LiteralPath 'tmp/last-deepseek-smoke-run.txt' -Raw).Trim()
& $taskPython -m macro run --config $deepseekConfig --cases data/benchmark-v2 --split dev --limit 1 --allow-paid-api --max-calls 48 --run-id $smokeRunId
if ($LASTEXITCODE -ne 0) { throw 'Smoke resume failed. Inspect the error before retrying.' }
& $taskPython -m macro summarize "results/$smokeRunId"
if ($LASTEXITCODE -ne 0) { throw 'Smoke report generation failed.' }
Start-Process -FilePath (Resolve-Path -LiteralPath "results/$smokeRunId/report.html").Path
```

## 8. The final 400-case evaluation

**Final-test inference requires an approved, matching readiness record.** A development run alone does not enable it. The completed agent source review, leakage review, development acceptance and frozen configuration are recorded under `readiness/deepseek-final-400/`. This is an agent review, not an independent human annotation study. The experiment is restricted to 400 factual base cases in both candidate orders; the recorded length-correlation limitation remains disclosed.

You can preview the final base-case workload now without making API calls:

```powershell
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split test --limit 400
if ($LASTEXITCODE -ne 0) { throw 'Final-test planning failed.' }
```

Expect **3,200 initial requests** and **19,200 maximum requests** with the current retry/tool settings. A completed final run has 800 evaluations per system and 400 candidate-order pairs per system. These counts cover the base cases only; adding explanation variants changes the workload.

The following is the paid final command, **only when `readiness/deepseek-final-400/final-readiness.json` has status `approved` and its hashes still match**. Use the frozen configuration. If a final run is already active, monitor it rather than starting another run. The runner rejects missing reviews, changed code/configuration, changed evidence, and a changed dataset.

```powershell
$finalRunId = 'deepseek-final-400-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
Set-Content -LiteralPath 'tmp/last-deepseek-final-run.txt' -Value $finalRunId

& $taskPython -m macro run --config configs/deepseek-final-400.json --cases data/benchmark-v2 --split test --limit 400 --allow-paid-api --max-calls 19200 --run-id $finalRunId --final-readiness readiness/deepseek-final-400/final-readiness.json
if ($LASTEXITCODE -ne 0) { throw 'Final run did not complete. Read the error and inspect saved results.' }

& $taskPython -m macro summarize "results/$finalRunId"
if ($LASTEXITCODE -ne 0) { throw 'Final report generation failed.' }
Start-Process -FilePath (Resolve-Path -LiteralPath "results/$finalRunId/report.html").Path
```

Do not tune prompts or settings using final-test model results and then treat a rerun as untouched final evidence.

## Optional: use DeepSeek thinking mode

For a separate development experiment, **replace the first configuration-selection line in section 3** with this line:

```powershell
$deepseekConfig = 'configs/deepseek-thinking-pilot.json'
```

Do not subsequently reset it to the thinking-disabled configuration. Use that variable throughout sections 3?5 with fresh run IDs. This configuration enables thinking with high effort, a 16,384-token response cap, and a 180-second timeout. The request-count caps remain the same, but token consumption and latency can differ.

If resuming a thinking-mode experiment, select the thinking configuration again; the resume block in section 7 otherwise selects the thinking-disabled configuration. Do not switch modes within an existing run. Freeze whichever configuration you select before final evaluation.

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| `DEEPSEEK_API_KEY is missing` | Repeat section 2. Save `.env` in the `MACRO` folder. |
| Authentication failure / HTTP 401 or 403 | Check the key and API account access. Fix credentials before retrying. |
| HTTP 429 | Check API limits, account credits, and saved call records before retrying. |
| `Model deepseek-flash is not found. The cost will be 0` from AutoGen | Current DeepSeek configurations supply custom prices. If this warning appears with an older/custom configuration, its local price entry is missing; zero is not an actual DeepSeek price. |
| `No module named macro` or a dependency import error | Follow the installation commands below, then repeat section 1 and the offline tests. |
| `technical_failure`, invalid JSON, or exhausted repairs | Inspect the report and `roles/`. A finished process can contain failed evaluations; do not count them as successful. |
| `Resume configuration ... changed` | Use a fresh run ID. Do not overwrite the saved manifest to force a resume. |
| `Interrupted requests have unknown billing/completion` | Inspect `calls/`; use `--retry-uncertain` only when you accept the possibility of repeating a billed request. |
| Final-test execution is disabled | Supply the approved `--final-readiness` record. If any frozen artifact changed, complete a new review/freeze instead of editing hashes to bypass the check. |
| `$taskPython` or a run-ID variable is empty | Repeat section 1. Recover saved IDs from the appropriate file under `tmp/`. |

### Fresh installation or missing dependencies

These commands install Python packages and require internet access. If an environment already works, you do not need to reinstall it for each experiment.

For a fresh installation, first install Python 3.11 or newer with the Windows Python launcher, then paste:

```powershell
Set-Location -LiteralPath 'C:\Users\shane\Documents\NLP\group_project\MACRO'
$ErrorActionPreference = 'Stop'
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment. Install Python 3.11 or newer first.' }
$taskPython = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path

& $taskPython -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'MACRO installation failed.' }
& $taskPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
```

To repair missing dependencies in the environment already selected in section 1, run the last three `pip` commands with that `$taskPython`, without creating another environment. Then continue from section 2. Installation or environment changes require fresh experiment IDs rather than resuming an older run.
