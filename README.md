# MACRO

MACRO evaluates **two already selected recipe recommendations** against a user's requirements. It compares one structured AG2 judge with three independent specialists: preference, recipe attributes/constraints, and explanation quality. A fixed Python coordinator combines the specialists' findings; there are no discussion rounds.

The current package, `data/benchmark-v2/`, contains **400 test cases and 120 separate development cases**. The test set has 80 cases each of constraint violations, dominance, trade-offs, ties and both recommendations violating constraints. The code uses one shared [evaluation policy](EVALUATION_POLICY.md), including speed when explicitly declared.

## Set up

Use Python 3.11 or newer. Open PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
```

For an existing setup, keep your existing `.env`. Run commands from the project folder; `.env` takes precedence over the terminal environment. In PyCharm, select `.venv\Scripts\python.exe` as the interpreter. Shared judge settings are in [configs/benchmark-judges.json](configs/benchmark-judges.json).

## Choose DeepInfra, Ollama or OpenAI

For **DeepInfra**, put your DeepInfra API key in `.env`:

```dotenv
LLM_PROVIDER=deepinfra
DEEPINFRA_API_KEY=your-deepinfra-key
DEEPINFRA_MODEL=Qwen/Qwen3.5-9B
```

`LLM_PROVIDER` selects `deepinfra`, `ollama` or `openai` and takes precedence over the old `IS_LOCAL_LLM` flag. There is no automatic fallback between providers. Keys stay in `.env` and are not written into run manifests.

DeepInfra uses the existing AG2/OpenAI SDK dependencies; **no extra pip install is needed**. The [documented API endpoint](https://deepinfra.com/Qwen/Qwen3.5-9B/api?example=openai-python) is `https://api.deepinfra.com/v1/openai`. Your PC runs the evaluation code; DeepInfra runs the model. This does not use your OpenAI account or local GPU.

## 3. Try one case

DeepSeek is also supported for the historical pilot with
[configs/deepseek-pilot.json](configs/deepseek-pilot.json). Set `DEEPSEEK_API_KEY`
in your existing `.env` or terminal environment; credentials are selected by
provider, with `.env` taking precedence. Commands must run from this directory.
Configurations without `provider` still select OpenAI.

```powershell
.\venv\Scripts\python.exe -m macro plan --config configs/deepseek-pilot.json --cases data/pilot --limit 1
# Paid development check, only when ready to spend API credits:
.\venv\Scripts\python.exe -m macro run --config configs/deepseek-pilot.json --cases data/pilot --limit 1 --allow-paid-api --max-calls 24 --run-id deepseek-pilot-001
```

Thinking must be explicitly configured. `configs/deepseek-pilot.json` disables it;
`configs/deepseek-thinking-pilot.json` enables it with high effort, a 16,384-token
cap and a 180-second timeout for every judge role. See Section 8 of
[DEEPSEEK_MIGRATION.md](DEEPSEEK_MIGRATION.md#8-thinking-enabled-execution-implemented)
for protocol handling, offline tests and a bounded smoke-run command.
DeepSeek uses JSON-object output with
local schema validation; OpenAI retains native schema enforcement. Both receive
the same schema instructions under prompt version `pilot-v3-provider`. Use fresh
run IDs after this migration. Pricing is unset, so reports show usage without a
monetary estimate; AG2's unknown-model zero cost is not an actual price. Offline
tests verify serialization, not live endpoint compatibility. See
[the migration status](DEEPSEEK_MIGRATION.md) for verification and pending work.

Start with a small compatibility run, then inspect its HTML report before the 400 cases:

```powershell
.\.venv\Scripts\python.exe -m macro plan --cases data/benchmark-v2/dev --limit 3
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --cases data/benchmark-v2/dev --limit 3 --max-calls 144 --run-id deepinfra-dev-01
```

The plan command is free and does not need an API key. The run command makes paid requests. DeepInfra's BF16 deployment differs from the local Ollama artifact: use a fresh run ID, keep local development results separate, and run both benchmark methods on the same provider/model/settings. Runs remain sequential.

For **local Ollama**, start the Ollama application (or `ollama serve` if it is not already running) and use `ollama list` to find your downloaded model's exact name. Set:

```dotenv
LLM_PROVIDER=ollama
IS_LOCAL_LLM=true
LOCAL_LLM_MODEL=your-installed-model-name
```

Replace the example name with an installed model that supports **tool calling and structured JSON responses**. An OpenAI key is unnecessary in local mode. A blank model name is rejected; connection/model errors never trigger a fallback to OpenAI.

No additional pip installation is required beyond the project setup. AG2 uses the existing OpenAI client to reach Ollama's [OpenAI-compatible endpoint](https://docs.ollama.com/api/openai-compatibility) at `http://127.0.0.1:11434/v1`. The separate native `autogen[ollama]` adapter is not used. Ollama itself and a downloaded model must be installed separately.

Try one development case locally:

```powershell
.\.venv\Scripts\python.exe -m macro plan --cases data/benchmark-v2/dev --limit 1
.\.venv\Scripts\python.exe -m macro run --cases data/benchmark-v2/dev --limit 1 --max-calls 24 --run-id ollama-dev-01
```

Local runs do not require `--allow-paid-api`; `--max-calls` still bounds requests. If your PC needs longer per response, increase `timeout_seconds` in the judge configuration before starting a new run. Local mode uses temperature 0 and sends the configured output-token cap as `max_tokens`; OpenAI-specific reasoning settings are omitted. The same local model/settings apply to all four roles.

For **OpenAI**, set:

```dotenv
LLM_PROVIDER=openai
IS_LOCAL_LLM=false
OPENAI_API_KEY=your-api-key
```

The model then comes from `configs/benchmark-judges.json`; the other providers' model variables are ignored. If `LLM_PROVIDER` is absent/blank, existing setups still use `IS_LOCAL_LLM` (true for Ollama, false or absent for OpenAI).

## Preview the evaluation (no API charges)

The historical Ollama development review is recorded in [BENCHMARK_RUN.md](BENCHMARK_RUN.md). For DeepInfra, use the current instructions here and a new run ID.

```powershell
.\.venv\Scripts\python.exe -m macro plan
```

This validates the benchmark and previews all 400 test cases. Each case is evaluated in both A/B orders: **8 initial requests per case, 3,200 total**. Retries and calculator follow-ups can add requests. The coordinator makes no API calls.

## Run the judges with DeepInfra or OpenAI (incurs API charges)

First check a few development cases:

```powershell
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --cases data/benchmark-v2/dev --limit 3 --max-calls 144 --run-id deepinfra-dev-01
```

Then run the 400 test cases:

```powershell
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --cases data/benchmark-v2/test --limit 400 --max-calls 6000 --run-id deepinfra-benchmark-400-01
```

| Option | Meaning |
|---|---|
| `--cases` | Split folder; defaults to `data/benchmark-v2/test` |
| `--limit` | Number of cases; omitted means the whole selected split |
| `--config` | Judge settings; defaults to `configs/benchmark-judges.json` |
| `--allow-paid-api` | Required for DeepInfra and OpenAI; unnecessary for local Ollama |
| `--max-calls` | Required request cap; **not a money limit or usage prediction** |
| `--run-id` | Output folder name inside `results/` |

Use a new run ID after changing code, configuration or cases, including after this refactor. To resume an interrupted run with unchanged inputs and code, repeat its command and ID. Completed assessments are reused. Do not run two processes with the same ID. An uncertain request requires inspecting its saved call record before explicitly permitting a retry; it may already have been billed.

## Read the results

Open `results/<run-id>/report.html`. It is generated automatically and includes decisions, evidence, judge rationales, raw responses and warnings.

Reports and manifests identify the selected provider/model. Changing either requires a new run ID. Local runs record request counts, tokens and latency without applying OpenAI pricing; local electricity/hardware costs are not estimated. Keep different-model experiments separate when comparing single and specialist judges.

- `summary.json` and `report.md`: metrics and recorded inference usage. Money estimates require configured pricing.
- `roles/`: individual responses, validation errors and retries.
- `evaluations/`: single-judge and coordinator decisions, including raw findings and constraint verification.
- `calls/`: request records and token usage.
- `manifest.json` and snapshots: the code/configuration/input identity used for the run.

Rebuild reports without API calls:

```powershell
.\venv\Scripts\python.exe -m macro.evaluate_case_generation.benchmark
.\venv\Scripts\python.exe -m macro.evaluate_case_generation.benchmark --verify-only
```

The defaults create **120 development cases and 400 final test cases** under
`data/benchmark-v2/`, using `configs/benchmark-v2.json` and
[EVALUATION_POLICY.md](EVALUATION_POLICY.md). Read the generated benchmark README
for coverage and pending reviews. Gold references and source mappings are in its
`private/` folder; only the split's `cases.jsonl` belongs in judge input.
The runner now supports this profile schema through explicit split selection; see
[Section 9.1 of the migration guide](DEEPSEEK_MIGRATION.md#91-benchmark-integration-and-checks--20-october-2026).
Preview the 120 development cases without API calls:

```powershell
.\venv\Scripts\python.exe -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 120
```

`--split test --limit 400` supports a no-cost preview. Paid final-test execution
is disabled while manual review, leakage checks and final freeze remain pending.
Use the development split for smoke runs and configuration choices.
Each of the five case categories has 24 development and 80 final-test cases. Category
balance is distinct from verdict-label balance. The earlier 600-test-case draft remains
in `data/benchmark-v1/` for provenance; do not combine versions for evaluation.

| Folder inside `src/macro/` | Responsibility |
|---|---|
| `evaluate_case_generation/` | Prepare the HUMMUS subset and construct case pairs |
| `ai_agents/` | Shared rubric, role prompts, response schemas and AG2 calls |
| `coordinator/` | One fixed aggregation implementation in `aggregation.py` |
| `evaluation/` | Validate inputs, run experiments, resume and calculate metrics |
| `reporting/` | Generate readable reports from saved outputs |
| `shared/` | Deterministic reference policy, comparison and file helpers |

[cli.py](src/macro/cli.py) defines the commands. See [ARCHITECTURE.md](ARCHITECTURE.md) for the execution flow and [DATA_PREPARATION.md](DATA_PREPARATION.md) for source-data preparation. `macro validate` verifies the existing benchmark; `macro audit` and `macro generate` prepare new data without API calls and refuse to overwrite existing packages.

Historical pilot data and results remain for provenance and report viewing. The obsolete pilot evaluator has been removed; new evaluations use the current benchmark schema. Previously inspected pilot recipes remain excluded during new benchmark generation.
