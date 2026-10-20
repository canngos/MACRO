import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from macro.shared.io import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from macro.shared.config import openai_api_key, deepinfra_api_key, provider_config
from macro.ai_agents.agents import LiveProvider
from macro.coordinator.aggregation import AGGREGATION_VERSION, aggregate, comparisons, guard_single
from macro.reporting.summary import summarize
from macro.shared.comparison import swapped
from macro.ai_agents.prompts import BENCHMARK_PROMPT_VERSION, visible_case
from macro.ai_agents.schemas import AssessmentValidationError, response_schema
from macro.ai_agents.schemas import SCHEMAS, SCHEMA_VERSION
from .inputs import load_inputs


class BudgetExceeded(RuntimeError):
    pass


class CallRecorder:
    def __init__(self, folder, max_calls):
        self.folder, self.max_calls = Path(folder), max_calls
        self.folder.mkdir(parents=True, exist_ok=True)

    def reserve(self, count):
        if len(list(self.folder.glob("*.json"))) + count > self.max_calls:
            raise BudgetExceeded("Insufficient call budget to safely finish this role's bounded tool loop")

    def tool(self, call_id, entry):
        path = self.folder / (call_id + ".json")
        row = read_json(path)
        row.setdefault("executed_tools", []).append(entry)
        write_json(path, row)

    def begin(self, tag, role, messages):
        if len(list(self.folder.glob("*.json"))) >= self.max_calls:
            raise BudgetExceeded("Maximum request count reached; resume with a larger explicit --max-calls if desired")
        call_id = uuid.uuid4().hex
        write_json(self.folder / (call_id + ".json"), {"call_id": call_id, "tag": tag, "role": role,
            "status": "in_flight", "messages": messages, "started_utc": datetime.now(timezone.utc).isoformat()})
        return call_id

    def end(self, call_id, update):
        path = self.folder / (call_id + ".json")
        row = read_json(path)
        row.update(update)
        write_json(path, row)


def source_code_hashes():
    """Fingerprint every package module with a distinct relative path for safe resume."""
    package_root = Path(__file__).resolve().parents[1]
    return {p.relative_to(package_root).as_posix(): file_hash(p)
            for p in sorted(package_root.rglob("*.py"))}


def experiment_plan(folder, limit, config):
    cases, _, dataset = load_inputs(folder, limit, config)
    count = len(cases)
    initial = count * 2 * 4
    return {"cases": count, "dataset": dataset, "orders": 2, "single_initial_calls": count * 2,
            "specialist_initial_calls": count * 6, "total_initial_calls": initial,
            "maximum_with_all_retries_and_tool_rounds": initial * config["max_attempts"] * (config["max_tool_rounds"] + 1),
            "model": config["model"], "provider": config.get("provider", "openai"),
            "base_url": config.get("base_url"), "note": "Plan only; no model initialized or API called."}


def run(folder, config, limit=None, run_id=None, max_calls=None, retry_uncertain=False):
    """Run real AG2 judges. Test fixtures are supplied only through the private runner."""
    config = config if "provider" in config else provider_config(config)
    if config["provider"] == "deepinfra":
        deepinfra_api_key()
    elif config["provider"] == "openai":
        openai_api_key()
    elif config["provider"] != "ollama":
        raise ValueError("Unsupported LLM provider")
    return _run(folder, config, lambda recorder: LiveProvider(config, recorder), "live",
                limit, run_id, max_calls, retry_uncertain, split)


def _run(folder, config, provider_factory, mode, limit=None, run_id=None, max_calls=None, retry_uncertain=False):
    if type(max_calls) is not int or max_calls < 0:
        raise ValueError("Set an explicit nonnegative max_calls request cap")
    cases, refs, dataset = load_inputs(folder, limit, config)
    if mode == "live" and max_calls < len(cases) * 8:
        raise ValueError(f"max-calls must cover at least {len(cases) * 8} initial requests; add room for retries/tools")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
        raise ValueError("run-id must contain only letters, numbers, hyphens and underscores")
    run_dir = Path("results") / run_id
    source_hashes = source_code_hashes()
    identity = {"mode": mode, "config": config, "case_digest": digest(cases), "reference_digest": digest(refs),
                "dataset": dataset, "policy_version": dataset["policy_version"],
                "aggregation_version": AGGREGATION_VERSION,
                "prompt_version": BENCHMARK_PROMPT_VERSION, "code_hashes": source_hashes,
                "schema_version": SCHEMA_VERSION,
                "wire_schema_hashes": {role: digest(response_schema(role, cases[0])) for role in SCHEMAS},
                "schema_hashes": {k: digest(v.model_json_schema()) for k, v in SCHEMAS.items()}}
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        old = read_json(manifest_path)
        if old["identity_hash"] != digest(identity):
            raise ValueError("Resume configuration, cases, prompts, schemas or code changed. Use a new run ID.")
    else:
        write_json(manifest_path, {**identity, "identity_hash": digest(identity), "started_utc": datetime.now(timezone.utc).isoformat(),
                                  "concurrency": 1, "live_gate_passed": False})
        write_jsonl(run_dir / "cases.snapshot.jsonl", cases)
        write_jsonl(run_dir / "references.snapshot.private.jsonl", refs)
    for name in ["roles", "evaluations", "calls"]:
        (run_dir / name).mkdir(exist_ok=True)
    uncertain = []
    for path in (run_dir / "calls").glob("*.json"):
        call = read_json(path)
        orphan = False
        if "_attempt-" in call["tag"] and call["status"] in ["complete", "error"]:
            base, attempt_text = call["tag"].rsplit("_attempt-", 1)
            orphan = not (run_dir / "roles" / f"{base}_{call['role']}_{int(attempt_text):02d}.json").exists()
        if call["status"] == "in_flight" or orphan:
            uncertain.append(path)
    if uncertain and not retry_uncertain:
        raise ValueError("Interrupted requests have unknown billing/completion. Inspect calls and explicitly use --retry-uncertain to allow a repeat.")
    for p in uncertain:
        record = read_json(p)
        record["status"] = "interrupted_unknown" if record["status"] == "in_flight" else "completed_without_assessment"
        write_json(p, record)
    provider = provider_factory(CallRecorder(run_dir / "calls", max_calls))
    stop = False
    for original in cases:
        for order in ["original", "reversed"]:
            case = original if order == "original" else swapped(original)
            evidence = visible_case(case)
            tag = case["case_id"] + "_" + order
            records = {}
            for role in ["single", "preference", "attribute", "explanation"]:
                paths = sorted((run_dir / "roles").glob(tag + "_" + role + "_*.json"))
                old_records = [read_json(p) for p in paths]
                completed = [r for r in old_records if r["status"] == "ok"]
                if completed:
                    records[role] = completed[-1]
                    continue
                feedback = old_records[-1] if old_records else None
                for attempt in range(len(old_records), config["max_attempts"]):
                    started = time.perf_counter()
                    try:
                        options = {"feedback": feedback} if feedback and feedback.get("validation_errors") else {}
                        record = provider.assess(role, evidence, f"{tag}_attempt-{attempt+1:02d}", **options)
                    except BudgetExceeded:
                        stop = True
                        break
                    except Exception as exc:
                        record = {"status": "technical_failure", "error_type": type(exc).__name__,
                                  "http_status": getattr(exc, "status_code", None), "assessment": None,
                                  "tool_calls": [], "note": "Inspect call records for responses/usage; exception text omitted to protect secrets."}
                        if isinstance(exc, AssessmentValidationError):
                            record.update(validation_errors=exc.errors, raw=exc.raw)
                            if hasattr(exc, "repair_context"):
                                record["repair_context"] = exc.repair_context
                        if getattr(exc, "status_code", None) in [400, 401, 403, 404]:
                            stop = True
                    record.update({"case_id": case["case_id"], "order": order, "role": role, "attempt": attempt + 1,
                                   "elapsed_seconds": time.perf_counter() - started})
                    write_json(run_dir / "roles" / f"{tag}_{role}_{attempt+1:02d}.json", record)
                    records[role] = record
                    feedback = record
                    if stop:
                        break
                    if record["status"] == "ok":
                        break
                if role not in records and old_records:
                    records[role] = old_records[-1]
                if stop:
                    break
            if not stop:
                single = records.get("single", {})
                a = single.get("assessment") or {}
                result = {"case_id": case["case_id"], "order": order, "system": "single",
                    "status": single.get("status", "technical_failure"), "decision": a.get("decision"),
                    "attributes": a.get("attributes", []), "assessment": a}
                if result["status"] == "ok":
                    # Retain raw findings; apply the same public-fact hard-constraint check to both systems.
                    _, result["comparison_diagnostics"] = comparisons(a["preferences"], a["attributes"], a, case["profile"]["objectives"])
                    guard_single(result, case)
                write_json(run_dir / "evaluations" / (tag + "_single.json"), result)
                panel = aggregate(records, case)
                write_json(run_dir / "evaluations" / (tag + "_specialists.json"), {"case_id": case["case_id"], "order": order, "system": "specialists", **panel})
                print(f"{tag}: single={result['decision']} [{result['status']}], specialists={panel['decision']} [{panel['status']}]")
            if stop:
                break
        if stop:
            break
    summarize(run_dir)
    print(f"Run saved: {run_dir}; {'stopped at budget/configuration error; inspect summary' if stop else 'finished'}. Mode={mode}.")
    return run_dir
