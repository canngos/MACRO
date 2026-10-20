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

An explicit `provider` in a JSON configuration takes precedence. Otherwise, `LLM_PROVIDER` selects `deepinfra`, `ollama` or `openai` and takes precedence over the old `IS_LOCAL_LLM` flag. There is no automatic fallback between providers. Keys stay in `.env` and are not written into run manifests.

DeepInfra uses the existing AG2/OpenAI SDK dependencies; **no extra pip install is needed**. The [documented API endpoint](https://deepinfra.com/Qwen/Qwen3.5-9B/api?example=openai-python) is `https://api.deepinfra.com/v1/openai`. Your PC runs the evaluation code; DeepInfra runs the model. This does not use your OpenAI account or local GPU.

## 3. Try one case

DeepSeek is supported on the current benchmark with
[configs/deepseek-pilot.json](configs/deepseek-pilot.json). Despite its historical
filename, this configuration now runs the benchmark schema. Set `DEEPSEEK_API_KEY`
in your existing `.env` or terminal environment; `.env` credentials take precedence.
An explicit configuration provider keeps this command on DeepSeek even if a different
provider is selected in the environment.

```powershell
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 120
# Paid development smoke check; use a new run ID after the merge repair:
& $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 1 --allow-paid-api --max-calls 48 --run-id deepseek-dev-merge-smoke-001
& $taskPython -m macro summarize results/deepseek-dev-merge-smoke-001
```

Set `$taskPython` to your installed environment's Python executable before using these
commands. `configs/deepseek-thinking-pilot.json` enables thinking instead. Both modes
have offline SDK protocol coverage; changed prompts and schemas require fresh live
development checks. Pricing is unset, so recorded usage has no monetary estimate.
AutoGen's unknown-model zero cost is not an actual price.

The repaired merge uses `benchmark-assessment-v2` (positive `duration_minutes` findings)
and `benchmark-judges-v2`. New runs retain the merged shared constraint guardrail and
report raw decisions separately. The saved 120-case run predates that contract and
must remain separate; its reports can be rebuilt without altering its recorded decisions.
See [the merge repair review](MERGE_REPAIR_REVIEW.md) for verification and limitations.

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

For the current integration status, see [the merge repair review](MERGE_REPAIR_REVIEW.md). Use a new run ID for each changed provider, configuration or implementation.

```powershell
.\.venv\Scripts\python.exe -m macro plan
```

This validates the benchmark and previews all 120 development cases. Each case is evaluated in both A/B orders: **8 initial requests per case, 960 total**. Retries and calculator follow-ups can add requests. The coordinator makes no API calls.

## Run the judges with DeepInfra or OpenAI (incurs API charges)

First check a few development cases:

```powershell
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --cases data/benchmark-v2/dev --limit 3 --max-calls 144 --run-id deepinfra-dev-01
```

The 400 final-test cases can be previewed without inference:

```powershell
.\.venv\Scripts\python.exe -m macro plan --cases data/benchmark-v2/test --limit 400
```

Final-test inference is disabled while dataset review, leakage checks, and freeze remain
pending. Use development cases to settle the provider, prompts, and configuration first.

| Option | Meaning |
|---|---|
| `--cases` | Split folder; defaults to `data/benchmark-v2/dev` |
| `--split` | Optional `dev` or `test` when `--cases` names the package root |
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

Rebuild a saved report or verify the existing dataset without API calls:

```powershell
& $taskPython -m macro summarize results/deepseek-benchmark-dev-120-001
& $taskPython -m macro validate --cases data/benchmark-v2/dev
```

Generate a new benchmark package only when intentionally preparing new data;
`macro generate` refuses to overwrite existing packages.

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
