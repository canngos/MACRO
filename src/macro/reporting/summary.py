"""Rebuild JSON, Markdown and HTML reports from saved experiment records."""
from collections import Counter
from pathlib import Path

from macro.shared.io import read_json, read_jsonl, write_json
from macro.evaluation.metrics import compute


def summarize(run_dir):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    cases = read_jsonl(run_dir / "cases.snapshot.jsonl")
    refs = read_jsonl(run_dir / "references.snapshot.private.jsonl")
    results = {}
    for path in (run_dir / "evaluations").glob("*.json"):
        row = read_json(path)
        results[(row["case_id"], row["order"], row["system"])] = row
    benchmark = manifest.get("policy_version") == "benchmark-policy-v1"
    final = benchmark and manifest.get("dataset", {}).get("split") == "test"
    report = {"mode": manifest["mode"], "is_model_performance": manifest["mode"] == "live",
              "warning": "OFFLINE FIXTURES ONLY: not evidence of judge reliability" if manifest["mode"] == "offline" else
                         "Benchmark test results; human review scheduled after inference" if final else "Development results; not final benchmark estimates",
              "metrics": compute(cases, refs, results)}
    if benchmark:
        report["raw_metrics"] = compute(cases, refs, {key: {**value, "decision": value.get("raw_decision", value["decision"])}
                                                     for key, value in results.items()})
        report["guardrails"] = {system: {"changed_decisions": sum(bool(r.get("guardrail_changed_decision"))
                                         for r in results.values() if r["system"] == system),
                                        "note": "Primary decisions use verified hard constraints. Raw metrics and raw constraint detection are retained."}
                                for system in ("single", "specialists")}
    calls = [read_json(p) for p in (run_dir / "calls").glob("*.json")]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for call in calls:
        for key in usage:
            usage[key] += (call.get("usage") or {}).get(key, 0)
    report["costs"] = {"model_calls": len(calls), "call_status_counts": dict(Counter(c["status"] for c in calls)),
        "retry_attempt_calls": sum('_attempt-' in c['tag'] and int(c['tag'].rsplit('_attempt-', 1)[1]) > 1 for c in calls),
        "calls_without_usage": sum(not c.get("usage") for c in calls), **usage,
        "latency_seconds_sum": sum(c.get("latency_seconds", 0) for c in calls),
        "tool_executions": sum(len(c.get("executed_tools", [])) for c in calls),
        "currency_estimate": None, "note": "All retry/tool-followup calls included. Unreported usage is unknown, not zero. No pricing configured."}
    pricing = manifest["config"].get("pricing")
    if pricing:
        # Optional verified configuration: uncached input upper estimate; never invent a price.
        for key in ["input_per_million", "output_per_million", "currency", "date", "source"]:
            if key not in pricing:
                raise ValueError("Pricing must include rates, currency, date and official source")
        report["costs"]["currency_estimate"] = usage["prompt_tokens"] * pricing["input_per_million"] / 1e6 + usage["completion_tokens"] * pricing["output_per_million"] / 1e6
        report["costs"]["pricing"] = pricing
        report["costs"]["note"] = "Uncached-input estimate for known usage only; unknown calls omitted and cache discounts not applied."
    report["costs_by_system"] = {}
    for system, roles in [("single", {"single"}), ("specialists", {"preference", "attribute", "explanation"})]:
        selected = [c for c in calls if c.get("role") in roles]
        totals = {key: sum((c.get("usage") or {}).get(key, 0) for c in selected) for key in usage}
        report["costs_by_system"][system] = {**totals, "model_calls": len(selected),
            "calls_without_usage": sum(not c.get("usage") for c in selected),
            "latency_seconds_sum": sum(c.get("latency_seconds", 0) for c in selected),
            "retry_attempt_calls": sum('_attempt-' in c['tag'] and int(c['tag'].rsplit('_attempt-', 1)[1]) > 1 for c in selected),
            "tool_executions": sum(len(c.get("executed_tools", [])) for c in selected),
            "currency_estimate": None if not pricing else
                (totals["prompt_tokens"] * pricing["input_per_million"] + totals["completion_tokens"] * pricing["output_per_million"]) / 1e6}
    write_json(run_dir / "summary.json", report)
    lines = ["# MACRO evaluation report", "", report["warning"], "", f"Mode: {manifest['mode']}. Run ID: {run_dir.name}.", "",
             "| System | Completed | Constraint precision | Constraint recall | Dominance accuracy | Priority alignment | Order stability |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    def rate(x):
        return "n/a" if x is None else f"{x:.3f}"
    for system, m in report["metrics"].items():
        lines.append(f"| {system} | {m['evaluation_coverage']['correct']}/{m['evaluation_coverage']['total']} | {rate(m['constraint_detection']['precision'])} | {rate(m['constraint_detection']['recall'])} | {rate(m['accuracy_by_type']['dominance']['rate'])} | {rate(m['declared_priority_alignment']['rate'])} | {rate(m['candidate_order_stability']['rate'])} |")
    lines += ["", "See summary.json for raw counts, all denominators, unresolved outcomes, failures and costs.",
              "Original/reversed results are repeated observations; they are not independent samples.",
              "The panel has three initial calls per case/order versus one for the single judge; this does not isolate specialization from additional computation.",
              "", f"Model calls: {len(calls)}. Currency estimate: {report['costs']['currency_estimate']}.",
              "Review coverage, raw findings and failures before interpreting accuracy. Human review is a separate validation step."]
    lines += ["", "## Inference costs", "", "| System | Requests | Input tokens | Output tokens | Summed latency (s) |", "|---|---:|---:|---:|---:|"]
    for system, cost in report["costs_by_system"].items():
        lines.append(f"| {system} | {cost['model_calls']} | {cost['prompt_tokens']} | {cost['completion_tokens']} | {cost['latency_seconds_sum']:.2f} |")
    if benchmark:
        lines += ["", "Primary accuracy uses the shared hard-constraint guardrail. Constraint precision/recall uses raw judge flags.",
                  "See raw_metrics in summary.json for accuracy before guardrails, and guardrails for changed-decision counts."]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    from .html_report import render_report
    render_report(run_dir, report)
    return report
