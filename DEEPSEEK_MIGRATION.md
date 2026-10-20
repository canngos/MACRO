# Switching the judge API from OpenAI to DeepSeek

**20 October merge repair:** the 120-case live development run has completed; see
[its review](DEEPSEEK_DEV_120_REVIEW.md). After merging main, the runtime now uses
the consolidated benchmark schema and shared constraint guardrails. Merge regressions
were repaired as documented in [the repair review](MERGE_REPAIR_REVIEW.md).
Use the current [README commands](README.md) and fresh run IDs. Historical pilot
execution commands and implementation snippets below are archival; their saved
results remain readable. Final-test inference remains disabled pending review/freeze.

Prepared 19 October 2026 against this repository's AG2 Classic implementation. **The initial provider migration is now applied and verified offline.** The snippets below remain as implementation reference; live service compatibility has not been verified and no paid API calls were launched.

**20 October update:** benchmark runner/prompt/schema/coordinator/report integration is now implemented and checked offline; see [Section 9.1](#91-benchmark-integration-and-checks--20-october-2026). The saved `deepseek-pilot-020` report also establishes that the historical 20-case live pilot was subsequently run (173 completed requests, full 40/40 evaluation coverage per system). Earlier implementation-status paragraphs below describe the 19 October work, not today's live-run history. No new paid calls or final-test model evaluation were launched during the 20 October integration.

## Implementation status — 19 October 2026

Completed the remaining initial-adapter work from original line 253 onward, preserving the existing Sections 3–5 edits:

- [x] Section 5 completion: assessments use `ag2_<provider>` labels. Advanced the shared prompt version to `pilot-v3-provider` for the already-added common JSON instructions.
- [x] Section 6: successful call records retain raw response/usage and now include provider, configured base URL, requested/returned model and thinking mode. SDK retries remain disabled; bounded retries, uncertain-call handling and configuration/source fingerprints remain intact. Pricing remains null.
- [x] Section 6: reject truncated, filtered, refused and unknown-finish responses as technical failures while retaining finish reasons in call records. Invalid JSON/schema never becomes a verdict. Reject unknown tools; malformed/non-object calculator arguments return a bounded tool error.
- [x] Section 7: added `tests/test_deepseek_provider.py` through the installed AG2/SDK path with networking blocked: all four roles, exact JSON/token/thinking fields, prompt consistency, metadata, calculator call IDs/results, ledger totals, usage accumulation, maximum rounds, malformed/empty output, refusal/truncation, exhausted schema repairs and safe HTTP error recording.
- [x] Section 7: credential tests cover both providers, file precedence, environment fallback, empty file values, unsupported providers, missing keys and cross-provider isolation. The historical missing-key runner test now mocks the working directory so workstation `.env` credentials cannot affect it.
- [x] Sections 9 and 11: both DeepSeek and OpenAI one-case `plan` commands passed without API requests: eight initial calls, maximum 48 with all configured retries/tool rounds. Added DeepSeek setup/preview/run guidance to `README.md`.
- [x] Section 10 offline check: `benchmark --out data/benchmark-v2 --verify-only` passed integrity, reference, swap and overlap checks. Its manual-review and leakage checks still report pending.

Pending by design: Section 8 thinking-enabled mode; Section 9 paid one-case/20-case pilots and their saved-report review; Section 10 benchmark policy/schema/runner integration, manual review, leakage checks and final evaluation. These are not marked done. Historical results and the user's local credentials were preserved. New experiments require fresh run IDs. Offline mocks establish adapter behavior, not endpoint/model availability or live JSON-plus-tools support.

Validation completed using `venv/Scripts/python.exe` (Python 3.14.3), without dependency changes:

- `-m unittest tests.test_deepseek_provider tests.test_config tests.test_response_contract`: **20 tests passed**.
- `-m unittest discover -s tests`: **61 tests passed**.
- `-m compileall -q src/macro`, `git diff --check`, and `-m pip check`: passed.
- Both one-case provider previews and the benchmark-v2 offline verification: passed as described above.

The installed AG2 emitted its expected unknown-model pricing warning for mocked DeepSeek responses and Python deprecation warnings; neither represents a provider price or live compatibility result. No paid run or final-test model evaluation was performed.

The smallest useful milestone is to run the existing 20-case pilot through DeepSeek. Running the new 400-case benchmark also requires policy/schema/runner integration, described separately below. Do not confuse successful provider connectivity with readiness for the final experiment.

## 1. What stays and what changes

Keep AG2 Classic (`autogen[openai]==0.14.1`), the OpenAI Python SDK and local Pydantic validation. DeepSeek exposes an OpenAI-compatible Chat Completions endpoint; using that SDK does not mean requests go to OpenAI. The endpoint and credential select the service. The snippets retain `api_type="openai"` as the protocol adapter.

| File | Edit |
| --- | --- |
| `.env.example`, local `.env` | Add `DEEPSEEK_API_KEY`; retain OpenAI credentials only if needed |
| `configs/deepseek-pilot.json` | New experiment settings, separate from benchmark-generation configuration |
| `src/macro/shared/config.py` | Select credentials by provider; retain backward compatibility |
| `src/macro/ai_agents/agents.py` | Provider-specific endpoint/parameters, common JSON instructions, dynamic provider label |
| `src/macro/evaluation/runner.py` | Provider-aware credential preflight and run identity |
| `src/macro/ai_agents/prompts.py` | Advance prompt version after modifying prompt construction |
| `tests/test_config.py`, new provider tests | Credential isolation, exact outbound request and tool/JSON handling |
| `src/macro/reporting/summary.py` | Usage metadata and optional DeepSeek cost accounting |
| `README.md` | Configuration and smoke-run commands |

All paths in this guide are relative to `MACRO/`. Commands are for PowerShell. Source and historical results should be preserved; use new run IDs after edits.

## 2. Prepare the environment

```powershell
Set-Location 'C:\Users\shane\Documents\NLP\group_project\MACRO'
git status --short
```

Use the existing virtual environment if available:

```powershell
$taskPython = '.\venv\Scripts\python.exe'
& $taskPython --version
& $taskPython -m pip check
```

On a new checkout, create a separate environment instead:

```powershell
python -m venv .venv
$taskPython = '.\.venv\Scripts\python.exe'
& $taskPython -m pip install -r requirements.lock.txt
& $taskPython -m pip install --no-deps -e .
```

Do not replace AG2 with Microsoft's similarly named packages or upgrade dependencies simply to change providers. First test the pinned versions. Any required dependency changes must be recorded and locked separately.

## 3. Configure the key and experiment

If `.env` does not exist, copy the example. Do not overwrite an existing key file:

```powershell
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
```

Add the following line to `.env` using an editor, replacing the placeholder locally. Also add the placeholder line to `.env.example`; do not put a real key there.

```dotenv
DEEPSEEK_API_KEY=replace-with-your-deepseek-key
```

Verify `.env` remains ignored without displaying its contents:

```powershell
git check-ignore .env
```

Create **`configs/deepseek-pilot.json`** with:

```json
{
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-flash",
  "thinking": "disabled",
  "max_tokens": 3500,
  "timeout_seconds": 120,
  "max_attempts": 2,
  "max_tool_rounds": 2,
  "pricing": null
}
```

The timeout and token cap above are initial engineering choices, not measured requirements. Adjust on development results and then fix them for evaluation. This configuration is for `plan`/`run`, not the `audit`/`generate` dataset commands. `configs/benchmark-v2.json` controls case counts; it is not an API configuration.

The cited DeepSeek documentation currently names `deepseek-flash` and `deepseek-v4-pro`. Confirm availability before the experiment and record the returned model identifier and date; aliases can change. Start with **thinking explicitly disabled** to avoid silently relying on a default and to keep the first migration small. A thinking-enabled experiment requires additional protocol testing in Section 8.

## 4. Make credentials provider-aware

Replace **`src/macro/shared/config.py`** with:

```python
"""Runtime credentials; never include key values in logs or errors."""
import os
from pathlib import Path
from dotenv import dotenv_values


def api_key(config):
    provider = config.get("provider", "openai")
    names = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
    if provider not in names:
        raise ValueError(f"Unsupported provider: {provider}")
    name = names[provider]
    value = dotenv_values(Path.cwd() / ".env").get(name) or os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing; set it in the project's .env file")
    return value


def openai_api_key():
    # Compatibility with historical callers/tests; new runtime calls pass config.
    return api_key({"provider": "openai"})
```

In **both** `ai_agents/agents.py` and `evaluation/runner.py`, change:

```python
from macro.shared.config import openai_api_key
```

to:

```python
from macro.shared.config import api_key
```

In `LiveProvider.assess()`, change `key = openai_api_key()` to:

```python
key = api_key(self.config)
```

In `evaluation/runner.py`'s public `run()` function, change the credential preflight to:

```python
api_key(config)
```

Do not silently use an OpenAI key when DeepSeek is selected. Keep the current `.env`-before-environment precedence and document that commands run from the project directory.

## 5. Build provider-specific requests and common JSON instructions

Add these helpers to **`src/macro/ai_agents/agents.py`**, keeping its existing imports of `json`, `prompt`, `response_schema`, and `validate_assessment`:

```python
def llm_settings(config, key, schema):
    provider = config.get("provider", "openai")
    common = {
        "api_type": "openai",
        "model": config["model"],
        "api_key": key,
        "max_retries": 0,
        "timeout": config["timeout_seconds"],
        "stream": False,
    }
    if provider == "deepseek":
        if config.get("thinking") != "disabled":
            raise ValueError("This initial adapter requires explicit thinking=disabled")
        return {
            **common,
            "base_url": config.get("base_url", "https://api.deepseek.com"),
            "max_tokens": config["max_tokens"],
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    if provider == "openai":
        return {
            **common,
            "reasoning_effort": config["reasoning_effort"],
            "max_completion_tokens": config["max_completion_tokens"],
            "response_format": schema,
            "store": False,
        }
    raise ValueError(f"Unsupported provider: {provider}")


def schema_example(node, root):
    """Illustrative wire shape, never a reference answer."""
    if "$ref" in node:
        return schema_example(root["$defs"][node["$ref"].split("/")[-1]], root)
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    if kind == "object":
        return {name: schema_example(child, root)
                for name, child in node.get("properties", {}).items()}
    if kind == "array":
        return [schema_example(node["items"], root)]
    if kind == "boolean":
        return False
    if kind in ("number", "integer"):
        return node.get("minimum", 0)
    return "Illustrative value; replace using supplied evidence"


def provider_prompt(role, evidence):
    system, user = prompt(role, evidence)
    schema = response_schema(role, evidence)
    system += (
        "\nReturn one JSON object matching this JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\nIllustrative JSON structure only; do not copy its values as findings:\n"
        + json.dumps(schema_example(schema, schema), ensure_ascii=False)
        + "\nDetermine all values from the supplied evidence and policy."
    )
    return system, user
```

The example helper targets the repository's current pilot wire schemas; test/extend it if the future benchmark schemas add `anyOf`, nullable unions or other constructs. It is a formatting example, not a claim of semantic consistency or a gold answer. The real local validator remains authoritative for assessment structure.

Replace the existing **`make_agent()` function** with:

```python
def make_agent(role, config, api_key, evidence=None):
    from autogen import ConversableAgent, LLMConfig
    schema = response_schema(role, evidence)
    system, _ = provider_prompt(role, evidence or {})
    agent = ConversableAgent(
        name=role + "_judge",
        system_message=system,
        human_input_mode="NEVER",
        code_execution_config=False,
        llm_config=LLMConfig(
            llm_settings(config, api_key, schema), cache_seed=None
        ),
    )
    agent.register_for_llm(name="calculate", description=calculate.__doc__)(calculate)
    return agent
```

Inside **`LiveProvider.assess()`**, replace:

```python
system, user = prompt(role, evidence)
```

with:

```python
system, user = provider_prompt(role, evidence)
```

This ensures the logged system prompt matches the one sent to the model. Apply the common JSON instructions to both providers in any new comparison experiment. Changing prompts requires advancing `PROMPT_VERSION` in `ai_agents/prompts.py`, for example to `pilot-v3-provider`, and using new run IDs. Do not compare a newly augmented DeepSeek prompt against historical OpenAI results as if only the model changed.

Replace the hardcoded `"provider": "ag2_openai"` in the returned record with:

```python
"provider": "ag2_" + self.config.get("provider", "openai")
```

Keep the bounded tool rounds, request recorder, local `validate_assessment()` call and targeted repair feedback. Do not turn parsing/schema failures into tie or insufficient-information verdicts.

Why JSON-object mode? The official guide documents that request shape, while this repository currently sends a strict schema through AG2. The installed AG2 client has a special path preserving `{"type":"json_object"}`; other schema dictionaries are wrapped as strict `json_schema` requests. This is a conservative compatibility route, not a claim that every DeepSeek endpoint lacks native schema support. Verify the actual outgoing request in Section 7.

## 6. Preserve errors, metadata and experiment identity

Keep SDK retries disabled so the project's existing recorder and bounded retry loop account for requests. A request failure may already have consumed provider resources; retain the existing uncertain-request handling rather than automatically replaying everything.

Keep these checks or add equivalent safe failures:

- Empty content, invalid JSON and invalid schema: record the failure; only retry through the configured attempt limit.
- `length` finish reason: incomplete output, not a usable assessment.
- Filter/refusal/provider-specific failure: preserve as a technical failure with finish reason; do not silently drop it.
- Unknown tool names and invalid arguments: reject or return the bounded tool error as the existing implementation does.
- HTTP errors: record safe type/status and usage if known; do not persist credentials or raw request headers.

In `recorded_create()`, extend the `self.recorder.end()` success payload with:

```python
"provider": self.config.get("provider", "openai"),
"base_url": self.config.get("base_url"),
"requested_model": self.config["model"],
"returned_model": data.get("model"),
"thinking": self.config.get("thinking"),
```

The existing `response` and `usage` values should remain. Raw provider responses may contain additional fields. Reports should display returned rationale/final findings, not reasoning content. If thinking support is later enabled, decide explicitly whether/how raw reasoning is retained; never mistake it for the final answer.

The runner already fingerprints the whole configuration and source modules. Supplying provider, endpoint, model and thinking mode in the config makes them part of its resume identity. Never put the key in that config or identity. Keep fresh run IDs across provider, prompt, code or model changes.

For costs, `reporting/summary.py` already supports `input_per_million`, `output_per_million`, `currency`, `date`, `source`. Keeping `pricing: null` means token/latency reporting without an invented monetary estimate. For a measured cost breakdown, separately account for provider-reported cache-hit/cache-miss input and reasoning usage when available. Preserve unknown usage as unknown; token counts from different tokenizers are not directly identical units. Check current official prices before filling rates.

The pinned AG2 version may warn that an unfamiliar model has zero estimated cost. This is a missing built-in price entry, not a free request or necessarily an unavailable model. Use the project's explicit pricing/usage records; never report AG2's fallback zero as actual experiment cost.

## 7. Verify offline before paying for any calls

First check syntax after applying all code edits:

```powershell
& $taskPython -m compileall -q src/macro
git diff --check
```

Add **`tests/test_deepseek_provider.py`**. The following test checks the installed AG2/SDK path without contacting the service:

```python
import json
import socket
import tempfile
import unittest
from unittest.mock import patch
from openai.types.chat import ChatCompletion
from openai.resources.chat.completions import Completions
from macro.ai_agents.agents import LiveProvider
from macro.ai_agents.prompts import visible_case
from macro.evaluation.runner import CallRecorder
from tests.fixtures import OfflineProvider
from tests.test_pilot import fixture


class DeepSeekWireTests(unittest.TestCase):
    def test_json_contract_for_every_role(self):
        config = {
            "provider": "deepseek", "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com", "thinking": "disabled",
            "max_tokens": 3500, "timeout_seconds": 120,
            "max_attempts": 2, "max_tool_rounds": 2, "pricing": None,
        }
        evidence = visible_case(fixture())
        for role in ["single", "preference", "attribute", "explanation"]:
            with self.subTest(role=role):
                raw = OfflineProvider().assess(role, evidence, "fixture")["raw"]
                content = raw if isinstance(raw, str) else json.dumps(raw)
                response = ChatCompletion.model_validate({
                    "id": "mock", "object": "chat.completion", "created": 0,
                    "model": "deepseek-flash",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                              "total_tokens": 150},
                })
                with tempfile.TemporaryDirectory() as folder, \
                     patch("macro.ai_agents.agents.api_key", return_value="offline-placeholder"), \
                     patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")), \
                     patch.object(Completions, "create", return_value=response) as sdk:
                    record = LiveProvider(config, CallRecorder(folder, 3)).assess(
                        role, evidence, "offline-check"
                    )
                    wire = sdk.call_args.kwargs
                    self.assertEqual(wire["response_format"], {"type": "json_object"})
                    self.assertEqual(wire["max_tokens"], 3500)
                    self.assertEqual(wire["extra_body"]["thinking"]["type"], "disabled")
                    self.assertNotIn("store", wire)
                    self.assertNotIn("max_completion_tokens", wire)
                    self.assertNotIn("reasoning_effort", wire)
                    self.assertEqual(record["status"], "ok")
                    self.assertEqual(record["provider"], "ag2_deepseek")
```

Also add credential tests covering both providers, `.env` precedence, environment fallback, unsupported providers, missing keys and no accidental cross-provider fallback. Mock both the environment and `Path.cwd()` in missing-key tests: the historical runner test currently clears the environment but can still discover a real local `.env` file. Make that test independent of workstation credentials; do not remove the user's `.env` to make it pass.

Extend the existing mocked tool-round tests for DeepSeek: calculator request, tool result with matching call ID, final valid JSON, total ledger count, usage accumulation and maximum-round failure. Add empty/malformed JSON, truncated output and failed-schema repair tests. If JSON mode plus tools is rejected by the selected live model, do not silently disable tools in only one comparison arm: test a documented compatible request strategy and disclose the resulting interface change.

Run the focused suite, then the existing suite:

```powershell
& $taskPython -m unittest tests.test_deepseek_provider tests.test_config tests.test_response_contract
& $taskPython -m unittest discover -s tests
```

A passing mock proves adapter behavior, not live endpoint compatibility. If `LLMConfig` or the SDK rejects a field locally, inspect the pinned library's accepted configuration and the exact mocked outgoing request. Do not assume that an OpenAI-compatible server implies all AG2 integrations are interchangeable.

## 8. Thinking-enabled execution (implemented)

Implemented 19 October 2026 in the current working tree. The initial disabled-only snippet in Section 5 describes the baseline migration; **do not replace the current thinking-capable helper with that older snippet**. `src/macro/ai_agents/agents.py` is now the authoritative implementation. The existing `configs/deepseek-pilot.json` still provides the thinking-disabled comparison condition.

### 8.1 Select the thinking configuration

Use the added **`configs/deepseek-thinking-pilot.json`**:

```json
{
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-flash",
  "thinking": "enabled",
  "reasoning_effort": "high",
  "max_tokens": 16384,
  "timeout_seconds": 180,
  "max_attempts": 2,
  "max_tool_rounds": 2,
  "pricing": null
}
```

Both the single judge and all specialists receive this same configuration. `high` is an explicit experimental choice, not a guarantee of optimal accuracy. Supported effort values are `low`, `high`, and `max`; missing/unknown modes or enabled-mode effort values fail validation. The initial 16,384-token cap and 180-second timeout are engineering budgets to validate on development cases. Freeze them before final evaluation. A larger budget is not silently granted when output truncates.

The provider-specific settings helper constructs:

```python
extra = {"thinking": {"type": mode}}
if mode == "enabled":
    extra["reasoning_effort"] = effort
# These are entries in the AG2 LLM settings:
settings = {
    "api_type": "openai",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "max_tokens": 16384,
    "response_format": {"type": "json_object"},
    "extra_body": extra,
}
```

`mode` and `effort` above are validated values from the configuration; this fragment illustrates the mapping rather than replacing the full `llm_settings()` function. The SDK merges `extra_body` fields into the top-level HTTP JSON. Effort is deliberately carried through that channel because the pinned AG2 Classic OpenAI effort enumeration does not accept DeepSeek's `max`. No OpenAI `store` or `max_completion_tokens` parameter is forwarded for DeepSeek. No temperature-based determinism is claimed in thinking mode.

### 8.2 Preserve transport history, including repairs

The implementation adds `thinking_enabled()` and `assistant_message()` in `ai_agents/agents.py`. It recovers assistant protocol fields from the SDK response captured by the call recorder, rather than relying on AG2's extracted final-answer string. Subsequent tool requests retain the complete sequence of assistant reasoning, tool-call IDs, arguments and tool results.

```python
# Simplified shape retained internally; values come from the actual SDK message.
messages.append({
    "role": "assistant",
    "content": sdk_message.get("content"),
    "reasoning_content": sdk_message["reasoning_content"],
    "tool_calls": sdk_message["tool_calls"],
})
```

This illustrative fragment covers a tool turn. Final assistant turns also retain reasoning when needed for a schema-repair continuation, even though they have no tool calls. A string-valued `reasoning_content` is required in thinking responses; an empty string is retained exactly, while a missing field causes a technical failure before executing that turn's tools. The adapter does not fabricate reasoning or silently switch modes.

If final JSON fails local validation, the adapter attaches an internal `repair_context` to `AssessmentValidationError`. The runner saves it in the failed role record so a bounded retry, including a resumed run, can reconstruct the original user message, every assistant/tool turn, and the invalid final assistant response before adding correction feedback. Already executed tools are not replayed merely to reconstruct context.

The context identity fingerprints role, public case evidence, configuration, system prompt and schema version. Mismatching histories are rejected rather than reused across cases, roles, providers or changed settings. Fresh assessments still start with fresh agents and histories. Existing run-identity checks continue to reject source/configuration changes under an old run ID.

### 8.3 Final output and usage reporting

Only final `content` is passed to `validate_assessment()` and becomes the judge's `raw` answer and structured findings. Reasoning is not treated as evidence, a verdict, or a rationale for scoring. Rendered HTML reports do not display reasoning text. Raw call records and failed-role repair contexts **do retain protocol reasoning** for audit and resumability; handle those artifacts accordingly. They are not public judge inputs or publication-ready transcripts.

Each completed call records provider, endpoint, requested/returned model, thinking mode, effort, raw provider usage, and latency. The JSON cost summary adds:

- `reported_reasoning_tokens`: sum of reported `completion_tokens_details.reasoning_tokens`, or `null` if no such breakdown was supplied.
- `calls_with_reasoning_token_breakdown`: number of calls contributing that field, so partial coverage is visible.

Reasoning tokens are already part of completion usage under this API; the summary does not add them again to total tokens or cost. An absent breakdown is unknown, not zero. Pricing remains unset unless verified rates are supplied.

Truncation, refusal, malformed JSON, invalid evidence pointers, unsupported tools, missing reasoning and exhausted tool/attempt budgets remain visible failures. The existing request cap is still a call-count cap, not a monetary cap.

### 8.4 Verify offline

From `MACRO/`, select the existing project environment:

```powershell
$taskPython = '.\venv\Scripts\python.exe'
& $taskPython -m unittest tests.test_deepseek_provider.DeepSeekThinkingTests
& $taskPython -m unittest discover -s tests
& $taskPython -m compileall -q src/macro
```

Use `.\.venv\Scripts\python.exe` if that is your environment instead. Thinking tests use mocked SDK responses with network connections blocked. They cover all four roles, effort/budget validation, multiple tool turns, empty versus missing reasoning, truncation, JSON-serialized repair history, role/case isolation, persistence through the runner, reasoning-token accounting and absence of reasoning in rendered reports. Existing disabled-mode and OpenAI tests should still pass. No live model compatibility or accuracy is established by mocks alone.

Verification on 19 October 2026: all **16 DeepSeek provider tests** and the full **68-test suite** passed offline. The thinking configuration's one-case `plan` command also succeeded and reported eight initial requests (up to 48 with all configured retries/tool rounds). No live evaluation was performed.

### 8.5 Preview and perform a small development smoke run

This request-count preview makes no model calls and does not require a valid API key:

```powershell
& $taskPython -m macro plan --config configs/deepseek-thinking-pilot.json --cases data/pilot --limit 1
```

When you choose to incur API charges, use a new ID:

```powershell
& $taskPython -m macro run --config configs/deepseek-thinking-pilot.json --cases data/pilot --limit 1 --allow-paid-api --max-calls 24 --run-id deepseek-thinking-smoke-001
& $taskPython -m macro summarize results/deepseek-thinking-smoke-001
```

Inspect JSON/schema validity, calculator continuations, failure coverage, usage and latency before scaling. A provider rejection of JSON mode plus tools must be investigated, not hidden by disabling tools for only one arm. Increase budgets only as an explicit development decision with a new run configuration/ID. No paid smoke run was launched during this implementation.

This configuration uses the existing **pilot runner**. It does not remove the new benchmark schema/runner incompatibilities described in Section 10, nor does it freeze the final 400-case dataset. Use development results to choose/fix mode, effort and budgets before the final test experiment.

## 9. Preview and run a small live pilot

These commands apply **after implementing and testing Sections 3-7**. The first makes no API requests:

```powershell
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/pilot --limit 1
```

Then, when ready to spend API credits, use a fresh run ID:

```powershell
& $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/pilot --limit 1 --allow-paid-api --max-calls 24 --run-id deepseek-pilot-001
```

One case in both orders has eight initial calls: two single-judge and six specialist calls. Retries/tool continuations add requests; `--max-calls` is a request cap, not a money cap. Stop for inspection if the cap is exhausted or outputs fail validation. Review the saved call records, each role's structured output, evidence pointers, failures and provider/model metadata. No paid call has been run as part of writing this guide.

Rebuild the saved report without new API calls:

```powershell
& $taskPython -m macro summarize results/deepseek-pilot-001
```

Once that works, a bounded 20-case development pilot can use:

```powershell
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/pilot --limit 20
& $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/pilot --limit 20 --allow-paid-api --max-calls 240 --run-id deepseek-pilot-020
```

The cap can legitimately stop a run if tool rounds/retries are frequent. Inspect records before changing the cap or resuming uncertain calls. New configuration/code requires a new run ID; unchanged interrupted runs may resume under the existing identity checks.

### 9.1 Benchmark integration and checks — 20 October 2026

The requested “400 validation cases” are actually `benchmark-v2`'s **400 final-test cases**, separate from **120 development cases**. Following the user's clarification, prepared and checked the integration while preserving the final cases: no final case was sent to a model, no paid API calls were made, and dataset files and historical run artifacts were not edited. Offline integrity/reference verification and a request-count preview are permitted without consuming the final split for model development.

Changes applied (paths relative to `MACRO/`):

- `src/macro/cli.py`, `evaluation/runner.py`: added explicit `--split dev|test` with `--cases` pointing to the benchmark root. Benchmark inputs load public `<split>/cases.jsonl` and separate `private/<split>.references.jsonl`; verify saved hashes, labels, swaps and overlaps before execution; reject missing/duplicate selected IDs or references. Removed the pilot's 20-case cap only for explicitly selected benchmark splits. Pilot commands retain their original policy and limit.
- `ai_agents/benchmark_schemas.py`, `ai_agents/schemas.py`: added a separate `benchmark-assessment-v1` contract with the five benchmark verdicts, active objectives, full/null priorities, nullable inactive preference scores, and negative-duration speed scores. Existing A/B coverage, feasibility/violation coherence and public evidence-pointer validation apply to all four roles. Invalid outputs remain technical failures.
- `ai_agents/prompts.py`, `ai_agents/agents.py`: added `benchmark-v1-provider` prompts for `benchmark-policy-v1`; explain null hard limits, active versus inactive objectives, speed, lexicographic priorities and explanation diagnostics. Public evidence remains explicitly whitelisted; private labels/categories/source mappings are never judge inputs. Extended illustrative schema rendering for nullable unions and negative speed values. Existing DeepSeek JSON mode, tools, bounded retries and thinking continuations remain shared.
- `ai_agents/benchmark_schemas.py`, `evaluation/runner.py`: benchmark coordination uses specialist-reported feasibility and scores, derives comparisons arithmetically, and applies feasibility, ties, dominance and priorities. It does not consult the reference evaluator or gold labels. Single-judge decisions are retained; disagreement between reported comparisons and numeric scores is diagnostic. Benchmark policy, prompt/schema, split, dataset-manifest hash, code/configuration and selected-case/reference identities are saved for safe resume. Use a fresh run ID after source/configuration changes.
- `evaluation/metrics.py`, `reporting/summary.py`, `reporting/html_report.py`: support the new reference layout and all five categories, overall and macro category accuracy, insufficient-information outcomes, full planned denominators, speed findings, null hard limits and recipes without titles. Missing/failed evaluations count against accuracy; both orders are repeated observations. Reports label benchmark integration/development results as nonfinal.
- `tests/test_benchmark_runner.py`: seven new offline tests cover hand-specified speed/priority/constraint/tie cases, inactive preference, malformed priorities/pointers, arithmetic on reported scores, missing specialist coverage, all four DeepSeek SDK request paths with networking blocked, full 120-case development persistence/report/resume, missing-result denominators, the 400-case preview, and the final-test execution guard.

Verification performed with the existing `venv/Scripts/python.exe`; no dependency changes:

- `-m unittest tests.test_benchmark_runner`: **7 tests passed**. The full development fixture pass covered **120 cases × two orders × four roles = 960 fixture assessments** and 240 evaluations per system. Fixtures use deterministic reference-shaped answers; their perfect agreement checks wiring and reporting, **not DeepSeek accuracy**. They make zero API requests; temporary fixture reports are removed by the test.
- `-m macro.evaluate_case_generation.benchmark --out data/benchmark-v2 --verify-only`: passed saved-artifact integrity, recomputed policy labels, order-swap/factual-template checks, and zero recipe/profile/case overlap. Manual review, explanation-length leakage and surface-classifier checks still report **pending**; explanation variants/source review and final freeze are also outstanding.
- The 400-case DeepSeek preview passed: **3,200 initial requests**, **19,200 maximum** with two attempts and two tool rounds. The 120-case development preview is 960 initial / 5,760 maximum requests. Request caps are not monetary caps; pricing stays unset.
- `-m unittest discover -s tests`: **75 tests passed** (68 existing plus seven benchmark integration tests). The final development persistence/report/resume test also passed after the HTML category-table update. The suite log is saved locally at `tmp/benchmark-integration-tests.log` (ignored by Git).
- `-m compileall -q src/macro`, `git diff --check`, and `-m pip check`: passed. The historical one-case DeepSeek pilot preview still reports eight initial / 48 maximum requests. `git diff --exit-code -- data` confirmed no dataset edits. Expected AG2 unknown-model pricing and Python deprecation warnings do not establish a provider price or live compatibility.

Reproduce the no-cost preparation checks from `MACRO/`:

```powershell
$taskPython = '.\venv\Scripts\python.exe'
& $taskPython -m unittest discover -s tests
& $taskPython -m macro.evaluate_case_generation.benchmark --out data/benchmark-v2 --verify-only
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 120
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split test --limit 400
```

A later **paid development smoke run**, not executed during this work, can use:

```powershell
& $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 1 --allow-paid-api --max-calls 48 --run-id deepseek-benchmark-dev-smoke-001
& $taskPython -m macro summarize results/deepseek-benchmark-dev-smoke-001
```

Inspect that saved run's schema validity, failures, tools, evidence, model metadata and usage before expanding to 120 development cases. The existing live 20-case pilot used the historical policy and does not establish benchmark prompt compatibility. `macro run --split test` currently refuses execution **before reading credentials or creating a provider**, even with `--allow-paid-api`; `plan --split test` is available. Final execution needs a separate change after review, leakage/variant decisions and dataset/configuration freeze, consistent with the user's instruction to preserve the final cases.

### 9.2 Instructions for the final 400-case validation run

The final operational step is to enable final-test execution **after development checks, review and freeze are complete**, then launch a new paid run. These instructions describe future work; they do not enable the guard or launch any API requests. The 400 cases are the final-test split, not an additional development/validation split.

1. **Validate live behavior on development cases.** Run the one-case development smoke command in Section 9.1 and review schema validity, evidence pointers, calculator continuations, failures, returned model metadata and usage. Once satisfactory, evaluate all 120 development cases. For the current disabled-thinking configuration:

   ```powershell
   & $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 120 --allow-paid-api --max-calls 5760 --run-id deepseek-benchmark-dev-120-001
   & $taskPython -m macro summarize results/deepseek-benchmark-dev-120-001
   ```

   Use development results to settle prompts, thinking mode, token/time limits, retry/tool limits and scoring. Changed code/configuration requires a fresh run ID. If choosing thinking-enabled mode, validate that configuration on development cases and use the same frozen configuration for the final run.

2. **Complete and record benchmark readiness.** Finish source/manual review, explanation-length leakage and surface-classifier checks. Decide whether the final study uses only the factual base explanations or the planned explanation variants; implement/review any required variants before freezing. Record review evidence and the final scope rather than changing pending flags without completing the checks. Additional variants require their own integration and request-budget calculation; the commands below cover only the 400 base cases in both orders.

3. **Enable reviewed final execution and freeze the experiment.** Replace the unconditional `split == "test"` rejection in `src/macro/evaluation/runner.py` with a checked final-readiness path; retain the explicit paid-API acknowledgement, split/private-reference separation, integrity checks and resume identity checks. Update `evaluation_status` and report warnings so a reviewed final run is identified correctly while development runs remain labeled development. Update the execution-guard tests to cover both rejection before readiness and execution after readiness. Run the full offline suite and static checks again. Freeze and record the dataset hashes, review evidence, source revision, policy/prompt/schema versions, selected DeepSeek configuration/model and date **before any final case is sent to a model**. Do not tune these settings using final-test results.

4. **Preview, then launch the frozen final run.** From `MACRO/`, use the frozen configuration and a fresh run ID. The example below assumes `configs/deepseek-pilot.json` is the configuration selected and frozen during development:

   ```powershell
   $taskPython = '.\venv\Scripts\python.exe'
   & $taskPython -m macro.evaluate_case_generation.benchmark --out data/benchmark-v2 --verify-only
   & $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split test --limit 400
   # FUTURE COMMAND: currently rejected by the final-test execution guard.
   # Run only after steps 1-3 are completed and recorded.
   & $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split test --limit 400 --allow-paid-api --max-calls 19200 --run-id deepseek-benchmark-final-400-001
   & $taskPython -m macro summarize results/deepseek-benchmark-final-400-001
   ```

   The base experiment requires **3,200 initial requests** (400 cases × two orders × four roles). With two attempts and two tool rounds, **19,200 requests** is the configured theoretical maximum. `--max-calls` caps requests, not money; select an affordable explicit cap before launch and recompute it if retry/tool limits or study arms change. Pricing is currently unset, so reports do not provide a monetary estimate.

5. **Inspect completion and preserve the final record.** Review `summary.json`, `report.html`, role failures and call records. Expected coverage is **800 evaluations per system** and 400 order pairs; report any missing/failed evaluations in the planned denominators. Report overall/per-category/macro accuracy, constraint diagnostics, insufficient-information outcomes, order stability, usage and latency. Preserve configuration, hashes, private references and raw records with the run. To resume an unchanged interrupted run, repeat its exact command with the same ID; inspect uncertain requests before explicitly opting into `--retry-uncertain`, since they may already have been billed. Do not run concurrent processes with the same ID. If final results prompt further development, disclose test-set reuse rather than treating those cases as untouched final evidence.

## 10. Separate work before the 400-case final evaluation

Do **not** point a historical pilot command directly at `data/benchmark-v2/test`. Section 9.1 now implements the integration below using explicit split selection; readiness for final model evaluation is still pending:

| Component | Required benchmark integration |
| --- | --- |
| Runner | Implemented: explicit split/private-reference loading and split-sized limits; final-test execution guarded |
| Profile/prompts | Implemented: `hard_max_duration_minutes`, active `objectives`, full/null `priorities`, speed semantics |
| Output schema | Implemented: benchmark verdicts/objectives, separate model/reference field handling |
| Coordinator | Implemented: benchmark-policy-v1 on model findings, independently of gold labels |
| Metrics/reports | Implemented: five categories, overall/macro accuracy, coverage, failures and new reference layout |
| Evidence | Implemented: only whitelisted public evidence goes to judges |
| Benchmark readiness | Finish manual review, explanation variants and leakage checks, then freeze data/prompts/configurations |

The offline benchmark integrity check is already available:

```powershell
& $taskPython -m macro.evaluate_case_generation.benchmark --out data/benchmark-v2 --verify-only
```

Develop on the **120 development cases** using the Section 9.1 commands. Keep the **400 final cases** untouched by model-result-driven changes. The CLI now previews either split and executes development cases; paid final-test execution remains deliberately disabled pending the outstanding reviews and freeze. Section 9.2 records the remaining work and the future final-run command.

For the current two-system architecture, 400 cases x two orders x four model roles means **3,200 initial calls** before retries/tools; 120 development cases mean 960. Explanation variants and additional systems multiply these counts. These are estimates, not permission to launch a run or statements that all study arms are implemented.

## 11. Switching back and preserving comparisons

The helper defaults configurations without `provider` to OpenAI, preserving `configs/pilot.json`. After applying the migration, an OpenAI preview still uses:

```powershell
& $taskPython -m macro plan --config configs/pilot.json --cases data/pilot --limit 1
```

A new OpenAI run must have a new ID because the shared prompts/code have changed. Historical records remain historical; do not rewrite their verdicts. For a provider comparison, hold evidence, criteria, response semantics, tools and retry rules fixed, and disclose native schema enforcement versus local-only enforcement as an interface difference. Report failures and costs alongside accuracy.

## References and validation status

Official documentation checked 19 October 2026:

- [DeepSeek API compatibility, endpoint and model names](https://api-docs.deepseek.com/).
- [DeepSeek JSON output requirements](https://api-docs.deepseek.com/guides/json_mode/).
- [DeepSeek thinking mode and continuation requirements](https://api-docs.deepseek.com/guides/thinking_mode/).
- [DeepSeek tool calls](https://api-docs.deepseek.com/guides/tool_calls/).
- [DeepSeek models and pricing](https://api-docs.deepseek.com/quick_start/pricing).

Repository basis: `ai_agents/agents.py`, `shared/config.py`, `evaluation/runner.py`, `ai_agents/schemas.py`, `reporting/summary.py`, current tests and pinned AG2's `autogen/oai/client.py`. The snippets are migration reference; the applied adapter is verified offline, not against the live service. Recheck model availability, compatibility and prices before a paid experiment.

Historical documentation-only verification on 19 October 2026, before implementation: the complete Python blocks passed syntax parsing. The documented helper/factory/assessment changes were assembled in memory and exercised through the installed AG2 and OpenAI SDK with mocked responses for all four roles. Assertions verified JSON-object format, DeepSeek token/thinking parameters, omission of OpenAI-specific request fields and successful local assessment validation. Network calls were blocked. Runtime source files were not changed by that earlier check; the implementation and verification status above supersedes it.
