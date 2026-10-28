# MACRO

MACRO evaluates fixed recipe recommendation pairs from HUMMUS. It compares a **structured single LLM judge** with **three independent specialist judges** (preference, attributes, and explanations), combined by a fixed Python coordinator. The specialists do not discuss their answers.

The course project asks how reliably judges handle constraints, dominance and trade-offs, and whether the specialist-panel system improves reliability. The benchmark contains **400 test cases and 120 separate development cases**.

## Start here

| To understand | Read |
|---|---|
| Evaluation rules and coordinator decisions | [Evaluation policy](EVALUATION_POLICY.md) |
| How the cases were constructed | [Data preparation](DATA_PREPARATION.md) |
| How the code fits together | [Architecture](ARCHITECTURE.md) |
| Recorded benchmark results and limitations | [Results](RESULTS.md) |
| Provider setup, evaluation and saved reports | [Running the project](documentation/RUNNING.md) |
| Independent review of 50 cases | [Human evaluation](HUMAN_EVALUATION.md) |

## Install

Use Python 3.11 or newer. From the repository folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

On macOS/Linux, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`. AG2 is installed as `autogen[openai]` by the requirements file.

## Inspect the benchmark without model calls

```powershell
.\.venv\Scripts\python.exe -m macro validate --cases data/benchmark-v2
.\.venv\Scripts\python.exe -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2/dev --limit 1
```

`validate` checks the saved cases and reference labels. `plan` previews the workload; neither needs an API key or starts a model. The explicit configuration makes this example independent of local provider settings. The historical `pilot` filename now refers to a configuration for the current benchmark.

## Run one development case

Choose a provider and configure `.env` using the [run guide](documentation/RUNNING.md). For example, after adding `DEEPSEEK_API_KEY`:

```powershell
.\.venv\Scripts\python.exe -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2/dev --limit 1 --allow-paid-api --max-calls 48 --run-id demo-01
```

This command makes paid API requests. Open `results/demo-01/report.html` afterward. Ollama runs locally and does not require `--allow-paid-api`. Each case has eight initial requests: four judge roles in each of two candidate orders. Retries and calculator follow-ups can add requests; the coordinator makes no model calls.

Final-test runs require a matching experiment-readiness record. See the run guide before attempting the 400-case evaluation.

## Repository layout

| Folder | Contents |
|---|---|
| `src/macro/` | Case generation, AG2 judges, coordinator, evaluation and reporting |
| `configs/` | Dataset and judge settings |
| `data/benchmark-v2/` | Current cases and separately stored reference labels |
| `tests/` | Software checks using fixtures and mocked model responses |
| `scripts/` | Human-review packet generation and experiment checks |
| `readiness/deepseek-final-400/` | Preserved review evidence for the frozen DeepSeek experiment |
| `documentation/archive/` | Historical development reviews; not required to run the project |

The Git repository includes the prepared data and code. Raw model logs in `results/`, completed human annotations, local credentials and the original HUMMUS CSV are not included by default. See [Results](RESULTS.md) for what the submitted summary covers.
