import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from macro.shared.io import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from macro.shared.config import api_key
from macro.ai_agents.agents import LiveProvider
from macro.coordinator.aggregation import AGGREGATION_VERSION, aggregate
from macro.reporting.summary import summarize
from macro.shared.policy import POLICY_VERSION, score_comparisons, swapped
from macro.ai_agents.prompts import PROMPT_VERSION, visible_case
from macro.ai_agents.schemas import SCHEMAS, SCHEMA_VERSION, AssessmentValidationError, response_schema


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
            raise BudgetExceeded("Maximum paid call count reached; resume with a larger explicit --max-calls if desired")
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
    count = min(limit, len(read_jsonl(Path(folder) / "cases.jsonl")))
    initial = count * 2 * 4
    return {"cases": count, "orders": 2, "single_initial_calls": count * 2,
            "specialist_initial_calls": count * 6, "total_initial_calls": initial,
            "maximum_with_all_retries_and_tool_rounds": initial * config["max_attempts"] * (config["max_tool_rounds"] + 1),
            "model": config["model"], "note": "Plan only; no model initialized or API called."}


def run(folder, config, limit=20, run_id=None, max_calls=240, retry_uncertain=False):
    """Run real AG2 judges. Test fixtures are supplied only through the private runner."""
    api_key(config)
    return _run(folder, config, lambda recorder: LiveProvider(config, recorder), "live",
                limit, run_id, max_calls, retry_uncertain)


def _run(folder, config, provider_factory, mode, limit=20, run_id=None, max_calls=240, retry_uncertain=False):
    if not 1 <= limit <= 20 or max_calls < 0:
        raise ValueError("Part 1 limit must be 1..20 and max_calls nonnegative")
    folder = Path(folder)
    all_cases = read_jsonl(folder / "cases.jsonl")
    cases = all_cases[:limit]
    refs = [r for r in read_jsonl(folder / "references.private.jsonl") if r["case_id"] in {c["case_id"] for c in cases}]
    if len(refs) != len(cases):
        raise ValueError("Missing references")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
        raise ValueError("run-id must contain only letters, numbers, hyphens and underscores")
    run_dir = Path("results") / run_id
    source_hashes = source_code_hashes()
    identity = {"mode": mode, "config": config, "case_digest": digest(cases), "reference_digest": digest(refs),
                "policy_version": POLICY_VERSION, "aggregation_version": AGGREGATION_VERSION,
                "prompt_version": PROMPT_VERSION, "code_hashes": source_hashes,
                "schema_version": SCHEMA_VERSION, "wire_schema_hashes": {role: digest(response_schema(role)) for role in SCHEMAS},
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
                    # Same consistency diagnostics for both systems; retain the single verdict.
                    _, result["comparison_diagnostics"] = score_comparisons(a["preferences"], a["attributes"], a)
                write_json(run_dir / "evaluations" / (tag + "_single.json"), result)
                panel = aggregate(records)
                write_json(run_dir / "evaluations" / (tag + "_specialists.json"), {"case_id": case["case_id"], "order": order, "system": "specialists", **panel})
                print(f"{tag}: single={result['decision']} [{result['status']}], specialists={panel['decision']} [{panel['status']}]")
            if stop:
                break
        if stop:
            break
    summarize(run_dir)
    print(f"Run saved: {run_dir}; {'stopped at budget/configuration error; inspect summary' if stop else 'finished'}. Mode={mode}.")
    return run_dir
