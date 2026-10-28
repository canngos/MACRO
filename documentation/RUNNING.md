# Running MACRO

Run commands from the repository root after the [installation steps](../README.md#install).
Examples use PowerShell and `.venv`; on macOS/Linux use `.venv/bin/python`.

## Select a provider

Create a local settings file without replacing an existing one:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` using one of the following options. Credentials are not committed or
included in saved run configuration. A provider explicitly selected in JSON takes
precedence over `LLM_PROVIDER`; `.env` values take precedence over terminal values.

| Provider | Settings in `.env` | Configuration |
|---|---|---|
| OpenAI | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...` | `configs/benchmark-judges.json` |
| Ollama | `LLM_PROVIDER=ollama`, `LOCAL_LLM_MODEL=qwen3.5:9b` | `configs/benchmark-judges.json` |
| DeepSeek | `DEEPSEEK_API_KEY=...` | `configs/deepseek-pilot.json` explicitly selects DeepSeek |
| DeepInfra | `LLM_PROVIDER=deepinfra`, `DEEPINFRA_API_KEY=...`, `DEEPINFRA_MODEL=Qwen/Qwen3.5-9B` | `configs/benchmark-judges.json` |

For OpenAI, the model comes from the JSON configuration. Ollama and DeepInfra use
their model variables above. Ollama must be running with the named model installed;
its endpoint is `http://127.0.0.1:11434/v1`. All providers use the installed AG2/OpenAI
client dependencies; no additional Python provider package is required.

Use a model that supports tools and structured output. Provider/model errors do not
trigger fallback to another provider. The legacy `IS_LOCAL_LLM` setting is consulted
only when `LLM_PROVIDER` and a JSON provider are absent.

## Preview and run development cases

`plan` validates inputs and reports request counts without inference:

```powershell
.\.venv\Scripts\python.exe -m macro plan --cases data/benchmark-v2/dev --limit 1
```

For OpenAI or DeepInfra, run one case after setting the provider:

```powershell
.\.venv\Scripts\python.exe -m macro run --cases data/benchmark-v2/dev --limit 1 --allow-paid-api --max-calls 48 --run-id demo-01
```

For DeepSeek, specify its configuration:

```powershell
.\.venv\Scripts\python.exe -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2/dev --limit 1 --allow-paid-api --max-calls 48 --run-id deepseek-demo-01
```

For local Ollama:

```powershell
.\.venv\Scripts\python.exe -m macro run --cases data/benchmark-v2/dev --limit 1 --max-calls 48 --run-id ollama-demo-01
```

Hosted `run` commands incur API charges; Ollama uses local compute. The default retry
and tool settings allow up to 48 requests per case, starting with eight initial
requests. `--max-calls` is a request cap, not a cost estimate. Use a new run ID for a
different model, configuration or implementation. Omit `--limit` to use all 120
development cases and set a suitable cap (5,760 covers the configured maximum).

## Inspect the output

Open `results/<run-id>/report.html` in a browser. A completed process can contain
failed assessments; check coverage as well as accuracy.

| Output | Contents |
|---|---|
| `report.html` | Decisions, judge rationales, evidence, raw responses and warnings |
| `report.md`, `summary.json` | Metrics, usage and configured cost estimates |
| `roles/` | Individual assessments, validation errors and attempts |
| `evaluations/` | Single/panel outcomes, raw decisions and constraint verification |
| `calls/` | Requests, provider responses and reported usage |
| `manifest.json`, snapshots | Exact configuration, code identity and input data |

Rebuild a report from saved records without calling a model:

```powershell
.\.venv\Scripts\python.exe -m macro summarize results/demo-01
```

This rewrites summary/report files, not recorded judgments. For a historical run,
work on a copy if its report files are part of frozen evidence. Configured prices
are dated estimates, not current tariffs or invoices. Unknown monetary cost must not
be interpreted as zero; local electricity/hardware costs are not measured.

## Resume

Repeat the original command and run ID with unchanged code, environment, settings
and data. Saved successful assessments are reused. Do not run two processes under
the same ID. If a request was interrupted with uncertain completion, inspect its
call record before adding `--retry-uncertain`, which can repeat a billed request.

## Final 400-case evaluation

Preview the test workload without credentials or model calls:

```powershell
.\.venv\Scripts\python.exe -m macro plan --config configs/deepseek-final-400.json --cases data/benchmark-v2/test --limit 400
```

The workload is 3,200 initial requests and at most 19,200 with the saved retry/tool
settings. There are 800 pair-level judgments per system, representing 400 base cases
in two orders.

Final inference requires `--final-readiness` with an approved record matching the
dataset, configuration, package code and supporting review/development files. The
historical record is [preserved here](../readiness/deepseek-final-400/REVIEW.md).
It depends on saved development-run artifacts under `results/`, which are not
included in a Git clone. A clone therefore supports validation, planning and new
development runs, but the historical final command needs those exact artifacts and
matching code. A changed experiment needs a new review/freeze; do not edit recorded
hashes merely to bypass the checks.

For the matching frozen DeepSeek experiment, the command is:

```powershell
.\.venv\Scripts\python.exe -m macro run --config configs/deepseek-final-400.json --cases data/benchmark-v2/test --limit 400 --allow-paid-api --max-calls 19200 --run-id deepseek-final-new --final-readiness readiness/deepseek-final-400/final-readiness.json
```

The original OpenAI/Qwen results used earlier prompts than the current DeepSeek
implementation. Current-code reruns are new experiments, not exact reproductions
of those earlier configurations. See [Results](../RESULTS.md).
