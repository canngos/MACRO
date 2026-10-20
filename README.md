# MACRO — Part 1

MACRO compares two ways of evaluating recipe recommendations with AG2:

- **Single judge:** one AI agent evaluates all criteria.
- **Specialist judges:** three independent AI agents evaluate preferences, recipe attributes and constraints, and explanations. A Python coordinator combines their findings using a fixed policy.

The current pilot contains **20 cases** built from real HUMMUS recipes and constructed user profiles: 7 constraint violations, 6 dominated recommendations (one option is at least as good on every objective and better on one), and 7 genuine trade-offs. This is a small demonstration before the larger course study.

The coordinator uses the judges' reported feasibility first, then dominance, then declared user priorities. A trade-off without enough priorities can remain unresolved. Reference answers are kept separate from agent inputs.

## 1. Set up

Use **Python 3.11 or newer**. Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

If you use PyCharm, select `.venv\Scripts\python.exe` as the project interpreter.

The prepared cases are in `data/pilot/`; you do not need to download the original dataset to run them. Read [the case preview](data/pilot/preview.md) for examples.

## 2. Set your API key

Copy `.env.example` to `.env` in the project folder:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `your-api-key` with your OpenAI API key:

```dotenv
OPENAI_API_KEY=your-api-key
```

Run commands from the project folder so the application can read `.env`. Its key takes precedence over `OPENAI_API_KEY` in the terminal environment, which remains a fallback. `.env` is excluded from Git. The model and other settings are in [configs/pilot.json](configs/pilot.json); the current model is `gpt-5-nano`.

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

**Preview the run — no API calls or charges:**

```powershell
.\.venv\Scripts\python.exe -m macro plan --limit 1
```

**Run the real AI judges — incurs OpenAI API charges:**

```powershell
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --limit 1 --max-calls 24 --run-id live-smoke-03
```

Here, `python -m macro` starts the project. `plan` previews the request count; `run` performs the evaluation.

| Option | Meaning |
|---|---|
| `--allow-paid-api` | Explicitly permits paid API calls |
| `--limit 1` | Evaluates one case |
| `--max-calls 24` | Caps API requests at 24; this is not a money limit |
| `--run-id live-smoke-03` | Saves this experiment under `results/live-smoke-03/` |

Each case is evaluated with both A/B and B/A ordering to check whether order changes the decision. That means **8 initial calls per case**: 2 single-judge calls and 6 specialist calls. Retries and tool follow-ups can add calls; reaching the cap can leave a run incomplete. The Python coordinator adds no API calls.

## 4. Run all 20 cases

After checking the one-case result:

```powershell
.\.venv\Scripts\python.exe -m macro run --allow-paid-api --limit 20 --max-calls 240 --run-id live-pilot-03
```

This starts with **160 model calls**, plus any retries or tool follow-ups within the request cap.

Use a **new run ID** for a new experiment or after changing code, settings, or cases. To resume an interrupted run, repeat its original command with the same ID; completed assessments are reused. Do not run two processes with the same ID at once. If the application reports an uncertain API request, inspect its saved call record before allowing a retry, since it may already have been billed.

## 5. Read the results

Open **`results/live-pilot-03/report.html`** in your browser (or `results/live-smoke-03/report.html` for the one-case run).

The HTML report is generated automatically. It shows decisions, each judge's explanation, evidence references, warnings, and expandable raw responses.

Other saved files include:

- `summary.json`: overall metrics and API usage.
- `roles/`: individual judge responses and errors.
- `evaluations/`: single-judge and coordinator decisions.
- `calls/`: API request records and usage.

To rebuild reports from an existing run **without making API calls**:

```powershell
.\.venv\Scripts\python.exe -m macro summarize results/live-pilot-03
```

## Prepare the larger recipe subset

The separate Phase 1 pipeline builds a versioned 5,000-recipe subset without changing
the historical pilot. Read [DATA_PREPARATION.md](DATA_PREPARATION.md) for the attribute
contract, filtering and ingredient-mapping limits. From this folder:

```powershell
.\venv\Scripts\python.exe -m macro.evaluate_case_generation.dataset --source ../pp_recipes/pp_recipes.csv --config configs/dataset-v1.json --out data/subset-v1
```

Use your environment's Python path if it differs. The command refuses to overwrite an
existing output folder. It creates recipes, an audit, distributions and a datasheet;
manual review and benchmark construction remain separate steps.

## Where to find the code

The new-policy benchmark is generated separately from the 20-case pilot:

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

| Folder inside `src/macro/` | Purpose |
|---|---|
| `evaluate_case_generation/` | Prepare recipes and evaluation cases |
| `ai_agents/` | AG2 agents, prompts, response schemas, and tools |
| `coordinator/` | Combine specialist findings using the fixed policy |
| `evaluation/` | Run experiments and calculate metrics |
| `reporting/` | Generate HTML, Markdown, and JSON reports |
| `shared/` | Common evaluation rules and file helpers |

[cli.py](src/macro/cli.py) defines the commands. See [ARCHITECTURE.md](ARCHITECTURE.md) for the detailed code guide and [PLAN.md](PLAN.md) for the project scope and phases.
