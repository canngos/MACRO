"""Shared no-cost preflight for planning and execution."""
from pathlib import Path
from macro.shared.io import read_json, read_jsonl


def load_inputs(folder, limit, config, split=None):
    folder = Path(folder)
    if split is not None:
        if split not in ("dev", "test"):
            raise ValueError("Benchmark split must be dev or test")
        if folder.name in ("dev", "test"):
            if folder.name != split:
                raise ValueError("--split disagrees with the selected split folder")
        else:
            folder = folder / split
    cases = read_jsonl(folder / "cases.jsonl")
    if not cases:
        raise ValueError("No evaluation cases")
    if limit is None:
        limit = len(cases)
    if type(limit) is not int or not 1 <= limit <= len(cases):
        raise ValueError(f"limit must be between 1 and {len(cases)}")
    if any("objectives" not in c.get("profile", {}) for c in cases):
        raise ValueError("Only the current benchmark schema is supported; use data/benchmark-v2/dev or test. Historical pilot files are archival.")
    if folder.name not in ("dev", "test"):
        raise ValueError("Benchmark folder must be its dev or test split")
    from macro.evaluate_case_generation.benchmark import verify_saved
    verify_saved(folder.parent)
    manifest = read_json(folder.parent / "manifest.json")
    if config.get("policy_version") != manifest["policy_version"]:
        raise ValueError("Use a configuration matching the benchmark policy_version")
    refs = read_jsonl(folder.parent / "private" / (folder.name + ".references.jsonl"))
    dataset = {"version": manifest["version"], "split": folder.name,
               "status": manifest["status"], "policy_version": manifest["policy_version"],
               "human_review": manifest.get("human_review", "pending")}
    ids = {c["case_id"] for c in cases}
    if len(ids) != len(cases) or len({r["case_id"] for r in refs}) != len(refs) or {r["case_id"] for r in refs} != ids:
        raise ValueError("Missing or duplicate case/reference IDs")
    cases = cases[:limit]
    refs = [r for r in refs if r["case_id"] in {c["case_id"] for c in cases}]
    token_key = "max_tokens" if config.get("provider") == "deepseek" else "max_completion_tokens"
    for key in ("max_attempts", token_key, "timeout_seconds"):
        if type(config.get(key)) is not int or config[key] <= 0:
            raise ValueError(key + " must be a positive integer")
    if type(config.get("max_tool_rounds")) is not int or config["max_tool_rounds"] < 0:
        raise ValueError("max_tool_rounds must be a nonnegative integer")
    return cases, refs, dataset
