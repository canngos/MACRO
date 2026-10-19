"""Readable, self-contained reports from saved results; no inference or result repair."""
import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from macro.shared.io import read_json, read_jsonl
from macro.shared.comparison import compare, swapped
from macro.ai_agents.prompts import visible_case


LABELS = {"single": "Single judge", "preference": "Preference judge",
          "attribute": "Attribute judge", "explanation": "Explanation judge"}
FIELDS = {"preference_score": "Preference score", "feasible": "Feasible",
          "violations": "Constraint violations", "nutrition_score": "Nutrition score", "duration_minutes": "Recorded duration (minutes)",
          "supported": "Explanation supported", "relevant_tradeoffs_disclosed": "Trade-offs disclosed",
          "issues": "Explanation issues"}
CSS = """
:root{color-scheme:light;--ink:#17263b;--muted:#526174;--line:#dce3eb;--accent:#185c91}
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:var(--ink);font:15px/1.55 system-ui,sans-serif}
main{max-width:1200px;margin:auto;padding:32px 24px 60px}h1{font-size:30px;margin:0}h2{font-size:23px}h3{font-size:19px}h4{font-size:16px;margin:0 0 10px}a{color:var(--accent)}
.muted{color:var(--muted)}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--accent);font-weight:700}
.panel,.case{background:white;border:1px solid var(--line);border-radius:12px;padding:22px;margin:20px 0}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.stat{background:white;border:1px solid var(--line);border-radius:10px;padding:16px}.stat strong{display:block;font-size:25px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.candidate{background:#f7f9fc;border-radius:8px;padding:16px}
.badge{display:inline-block;padding:3px 9px;border-radius:20px;background:#e7eef6;font-size:12px;font-weight:650;margin:3px 4px 3px 0}.ok{background:#e2f3e9;color:#165a34}.warn{background:#fff0d1;color:#805000}.bad{background:#fce6e6;color:#8e2727}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{background:#f4f7fb}td:first-child{font-weight:600}
.rationale{border-left:3px solid #7eabc9;padding:10px 14px;background:#f5f9fc;white-space:pre-wrap;overflow-wrap:anywhere}.alert{border-left:3px solid #d18b20;padding:12px 16px;background:#fff7e8;margin:12px 0}.alert ul{margin:4px 0;padding-left:20px}
details{border:1px solid var(--line);border-radius:8px;margin:12px 0;padding:12px}summary{cursor:pointer;font-weight:650}details[open]>summary{margin-bottom:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;border-radius:6px;padding:14px;max-height:480px;overflow:auto;font:12px/1.6 ui-monospace,Consolas,monospace}
.evidence a{display:block;font:12px/1.6 ui-monospace,Consolas,monospace;margin:4px 0}.fact:target{background:#fff0bc;outline:2px solid #dda822}.facts code{font-size:12px}.facts td{max-width:680px}.case-nav{display:flex;flex-wrap:wrap;gap:10px}code{overflow-wrap:anywhere}
@media(max-width:700px){main{padding:20px 12px}.stats,.grid{grid-template-columns:1fr}.case,.panel{padding:16px}h1{font-size:25px}}
@media print{body{background:white}main{max-width:none}.case{break-before:page}pre{max-height:none}.stats{grid-template-columns:repeat(4,1fr)}}
"""


def text(value):
    if value is None:
        return "Not reported"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(map(str, value)) if value else "None"
    return str(value)


def h(value):
    return escape(text(value), quote=True)


def pretty(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def badge(value):
    style = "ok" if value == "ok" else "warn" if value == "inconsistent_findings" else "bad"
    return f'<span class="badge {style}">{h(value)}</span>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th scope="col">{h(x)}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def disclosure(title, content):
    return f'<details><summary>{h(title)}</summary>{content}</details>'


def fact_id(prefix, pointer):
    return prefix + "-fact-" + pointer.encode("utf-8").hex()


def evidence_links(pointers, prefix):
    return '<div class="evidence">' + ''.join(f'<a href="#{h(fact_id(prefix, p))}">{h(p)}</a>' for p in pointers) + '</div>' if pointers else '<span class="muted">Not reported</span>'


def facts(value, prefix, pointer=""):
    rows = []
    if pointer:
        rows.append(f'<tr class="fact" id="{h(fact_id(prefix, pointer))}"><td><code>{h(pointer)}</code></td><td>{h(pretty(value) if isinstance(value, (dict, list)) else value)}</td></tr>')
    if isinstance(value, (dict, list)):
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, item in items:
            token = str(key).replace("~", "~0").replace("/", "~1")
            rows.extend(facts(item, prefix, pointer + "/" + token))
    return rows


def diagnostic_notes(assessment, case):
    """Display contradictions without changing the persisted assessment or decision."""
    notes = []
    for group, field, comparison in [("preferences", "preference_score", "preference_comparison"),
                                     ("attributes", "nutrition_score", "nutrition_comparison"),
                                     ("findings", "preference_score", "preference_comparison"),
                                     ("findings", "nutrition_score", "nutrition_comparison")]:
        values = {x.get("candidate"): x.get(field) for x in assessment.get(group, [])}
        if all(isinstance(values.get(k), (int, float)) for k in ["A", "B"]) and comparison in assessment:
            expected = compare(values["A"], values["B"])
            if assessment[comparison] != expected:
                notes.append(f"{comparison}: reported {assessment[comparison]}, but scores A={values['A']} and B={values['B']} imply {expected}.")
    for finding in assessment.get("attributes", assessment.get("findings", [])):
        slot = finding.get("candidate")
        if slot not in case["recommendations"] or "violations" not in finding:
            continue
        recipe = next(r for r in case["candidate_pool"] if r["id"] == case["recommendations"][slot]["recipe_id"])
        cap = case["profile"].get("hard_max_duration_minutes", case["profile"].get("max_duration_minutes"))
        if "duration" in finding["violations"] and (cap is None or recipe["duration_minutes"] <= cap + 1e-9):
            notes.append(f"{slot}: reported a duration violation, but the supplied duration does not exceed an active hard limit.")
    return notes


def role_card(record, role, case, prefix):
    assessment = record.get("assessment") or {}
    parts = [f'<article><h4>{h(LABELS[role])} · attempt {h(record.get("attempt"))}</h4>', badge(record.get("status")),
             ]
    if isinstance(record.get("elapsed_seconds"), (int, float)):
        parts.append(f'<span class="badge">{h(round(record["elapsed_seconds"], 2))} seconds</span>')
    notes = diagnostic_notes(assessment, case)
    if notes:
        parts.append('<div class="alert"><strong>Report diagnostics</strong><ul>' + ''.join(f'<li>{h(x)}</li>' for x in notes) + '</ul><small>These checks do not change the judge’s response or recorded outcome.</small></div>')
    for key in ["decision", "preference_comparison", "nutrition_comparison", "speed_comparison", "priority", "priorities"]:
        if key in assessment:
            parts.append(f'<span class="badge">{h(key.replace("_", " "))}: {h(assessment[key])}</span>')
    if assessment.get("rationale"):
        parts.append('<p><strong>Judge’s rationale</strong></p><div class="rationale">' + h(assessment["rationale"]) + '</div>')
    for group in ["findings", "preferences", "attributes", "explanations"]:
        if group not in assessment:
            continue
        by_slot = {x.get("candidate"): x for x in assessment[group]}
        rows = [[h(label), h(by_slot.get("A", {}).get(key)), h(by_slot.get("B", {}).get(key))]
                for key, label in FIELDS.items() if any(key in x for x in by_slot.values())]
        rows.append(["Evidence references", evidence_links(by_slot.get("A", {}).get("evidence", []), prefix), evidence_links(by_slot.get("B", {}).get("evidence", []), prefix)])
        parts.append(table([group.capitalize(), "Candidate A", "Candidate B"], rows))
    if record.get("validation_errors"):
        parts.append('<div class="alert"><strong>Validation errors</strong><pre>' + h(pretty(record["validation_errors"])) + '</pre></div>')
    if record.get("error_type"):
        parts.append(f'<p>Error: {h(record["error_type"])}. {h(record.get("note", ""))}</p>')
    parts.append(disclosure("Raw response · formatted for reading", '<pre>' + h(pretty(record.get("raw"))) + '</pre><p class="muted">Whitespace is formatted here. The exact returned text remains in the linked JSON record.</p>'))
    if "system_prompt" in record or "user_prompt" in record:
        parts.append(disclosure("Full instructions and input", '<h4>System instructions</h4><pre>' + h(record.get("system_prompt")) + '</pre><h4>Case input</h4><pre>' + h(pretty(record.get("user_prompt"))) + '</pre>'))
    if record.get("tool_calls"):
        parts.append(disclosure("Calculator executions", '<pre>' + h(pretty(record["tool_calls"])) + '</pre>'))
    parts.append('</article>')
    return ''.join(parts)


def render_report(run_dir, report=None):
    """Write only report.html. All saved model outputs and metrics stay untouched."""
    run_dir = Path(run_dir)
    report = report if report is not None else read_json(run_dir / "summary.json")
    manifest = read_json(run_dir / "manifest.json")
    cases = read_jsonl(run_dir / "cases.snapshot.jsonl")
    refs = {r["case_id"]: r for r in read_jsonl(run_dir / "references.snapshot.private.jsonl")}
    roles = {}
    for path in sorted((run_dir / "roles").glob("*.json")):
        row = read_json(path)
        roles.setdefault((row["case_id"], row["order"], row["role"]), []).append((path, row))
    evaluations = {}
    for path in (run_dir / "evaluations").glob("*.json"):
        row = read_json(path)
        evaluations[(row["case_id"], row["order"], row["system"])] = row
    cost = report["costs"]
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>MACRO · ' + h(run_dir.name) + '</title><style>' + CSS + '</style></head><body><main>',
             '<div class="eyebrow">MACRO / Evaluation</div><h1>Judge decision report</h1>',
             f'<p class="muted">Run {h(run_dir.name)} · {h(manifest["mode"])} · {h(manifest["config"].get("provider", "openai"))} · {h(manifest["config"].get("model"))}</p>',
             '<p class="muted">' + h(report["warning"]) + '</p><div class="stats">']
    for label, value in [("Cases", len(cases)), ("API requests", cost["model_calls"]), ("Total tokens", f'{cost["total_tokens"]:,}'), ("Retry requests", cost["retry_attempt_calls"])]:
        parts.append(f'<div class="stat"><span class="muted">{h(label)}</span><strong>{h(value)}</strong></div>')
    parts.append('</div><section class="panel"><h2>Run overview</h2>')
    overview = []
    for system, metric in report["metrics"].items():
        accuracy = metric["accuracy_by_type"]
        correct = sum(x["correct"] for x in accuracy.values())
        total = sum(x["total"] for x in accuracy.values())
        coverage = metric["evaluation_coverage"]
        stable = metric["candidate_order_stability"]
        overview.append([h("Single judge" if system == "single" else "Specialist panel"),
                         h(f'{coverage["correct"]}/{coverage["total"]}'), h(f'{correct}/{total}'),
                         h(metric["outcomes"].get("unresolved", 0) + metric["outcomes"].get("insufficient_information", 0)), h(f'{stable["correct"]}/{stable["total"]}'),
                         h(json.dumps(metric["diagnostic_counts"])),
                         h(f'{metric["comparison_consistency"]["evaluations_with_warnings"]}/{metric["comparison_consistency"]["checked_evaluations"]}'
                           if metric.get("comparison_consistency", {}).get("checked_evaluations") else "Not recorded")])
    parts.append(table(["System", "Completed evaluations", "Correct decisions", "Unresolved", "Stable order pairs", "Failures", "Comparison warnings / checked"], overview))
    parts.append('<p class="muted">Order stability means the same recipe or outcome after swapping A/B; repeated unresolved outcomes can be stable and incorrect. Order variants are repeated observations, not independent cases.</p>')
    parts.append(f'<p>Summed API latency: {cost["latency_seconds_sum"]:.2f} seconds · Requests without usage: {h(cost["calls_without_usage"])} · Tool executions: {h(cost["tool_executions"])} · Currency estimate: {h(cost["currency_estimate"])}</p>')
    if report.get("costs_by_system"):
        parts.append(table(["System", "Requests", "Input tokens", "Output tokens", "Summed latency (s)"],
            [[h(s), h(c["model_calls"]), h(c["prompt_tokens"]), h(c["completion_tokens"]), h(round(c["latency_seconds_sum"], 2))]
             for s, c in report["costs_by_system"].items()]))
    if report.get("raw_metrics"):
        parts.append('<p>Primary decisions use the shared hard-constraint guardrail. Constraint precision/recall uses raw judge findings.</p>')
        parts.append(table(["System", "Correct before guardrail", "Decisions changed by guardrail"],
            [[h(s), h(str(sum(x["correct"] for x in m["accuracy_by_type"].values())) + '/' + str(sum(x["total"] for x in m["accuracy_by_type"].values()))),
              h(report["guardrails"][s]["changed_decisions"])] for s, m in report["raw_metrics"].items()]))
    parts.append('<p><a href="summary.json">Full metrics JSON</a> · <a href="report.md">Markdown summary</a></p></section>')
    parts.append('<nav class="case-nav" aria-label="Cases">' + ''.join(f'<a href="#case-{i}">Case {i + 1}</a>' for i in range(len(cases))) + '</nav>')
    for i, original in enumerate(cases):
        cid = original["case_id"]
        parts.append(f'<section class="case" id="case-{i}"><h2>Case {i + 1} <span class="muted">· {h(cid)}</span></h2>')
        for order in ["original", "reversed"]:
            case = original if order == "original" else swapped(original)
            prefix = f'case-{i}-{order}'
            parts.append(f'<h3>{h(order.capitalize())} candidate order</h3><p>{h(case["request"])}</p><div class="grid">')
            for slot in ["A", "B"]:
                recommendation = case["recommendations"][slot]
                recipe = next(r for r in case["candidate_pool"] if r["id"] == recommendation["recipe_id"])
                parts.append(f'<div class="candidate"><h4>{slot} · {h(recipe.get("title", "Candidate " + slot))}</h4><p class="muted">Recipe {h(recipe["id"])}</p><p>{h(recipe["duration_minutes"])} minutes · Nutrition {h(recipe["nutrition_score"])}</p><p>Ingredient groups: {h(recipe["canonical_ingredients"])}</p><p>{h(recommendation["explanation"])}</p></div>')
            parts.append('</div>')
            result_rows = []
            for system in ["single", "specialists"]:
                result = evaluations.get((cid, order, system), {})
                decision = result.get("decision")
                recipe_id = case["recommendations"].get(decision, {}).get("recipe_id")
                result_rows.append([h("Single judge" if system == "single" else "Specialist panel"), badge(result.get("status", "missing")), h(decision), h(recipe_id), h(result.get("trace", []))])
                if "verified_constraints" in result:
                    parts.append(disclosure(system + " · raw decision and verified constraints",
                        '<pre>' + h(pretty({k: result.get(k) for k in ("raw_decision", "decision", "guardrail_changed_decision", "verified_constraints")})) + '</pre>'))
            parts.append(table(["System", "Status", "Recorded decision", "Chosen recipe ID", "Coordinator trace"], result_rows))
            panel = evaluations.get((cid, order, "specialists"), {})
            if "derived_comparisons" in panel:
                parts.append('<p class="muted">Coordinator: hard constraints verified from public facts; then active-objective comparisons derived from specialist-reported scores and declared user priorities. Scores remain model-reported.</p>' if "verified_constraints" in panel else '<p class="muted">Historical pilot: feasibility and scores are model-reported, not independently verified by the coordinator.</p>')
                parts.append(table(["Criterion", "Judge reported", "Coordinator calculated"],
                    [[h(field.replace("_comparison", "").capitalize()), h(panel["reported_comparisons"][field]), h(value)]
                     for field, value in panel["derived_comparisons"].items()]))
            if panel.get("comparison_diagnostics"):
                parts.append('<div class="alert"><strong>Coordinator comparison warnings</strong><ul>' + ''.join(
                    f'<li>{h(d["criterion"])}: judge reported {h(d["reported"])}, scores imply {h(d["derived"])}.</li>'
                    for d in panel["comparison_diagnostics"]) + '</ul>The original responses are preserved below.</div>')
            parts.append(disclosure("Supplied facts · evidence link destinations", '<div class="scroll"><table class="facts"><thead><tr><th>Evidence path</th><th>Supplied value</th></tr></thead><tbody>' + ''.join(facts(visible_case(case), prefix)) + '</tbody></table></div>'))
            for role in LABELS:
                attempts = sorted(roles.get((cid, order, role), []), key=lambda item: item[1].get("attempt", 0))
                cards = []
                for path, record in attempts:
                    cards.append(role_card(record, role, case, prefix))
                    cards.append(f'<p><a href="{h(quote(path.relative_to(run_dir).as_posix(), safe="/"))}">Open saved JSON · {h(path.name)}</a></p>')
                parts.append(disclosure(f'{LABELS[role]} · {len(attempts)} saved attempt(s)', ''.join(cards) if cards else '<p class="muted">No saved assessment. The run may be incomplete.</p>'))
        ref = refs.get(cid, {})
        parts.append(disclosure("Evaluation reference · separate from agent inputs", '<p class="muted">This reference is used to evaluate outputs. It was not supplied to the judges. A/B below use the original order.</p><pre>' + h(pretty(ref)) + '</pre>'))
        parts.append('</section>')
    parts.append('<footer class="muted">Generated locally from saved results. No API requests are made to build this report. The rationale is the judge’s returned justification; this report does not expose hidden model reasoning.</footer></main>')
    # Opening ancestors makes evidence links work even when fact sections are collapsed.
    parts.append('''<script>
function revealEvidence(){let id;try{id=decodeURIComponent(location.hash.slice(1))}catch{return}
let target=document.getElementById(id)||document.getElementById(location.hash.slice(1));
if(!target)return;for(let p=target.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
target.scrollIntoView({block:'center'});}
window.addEventListener('hashchange',revealEvidence);revealEvidence();
</script></body></html>''')
    path = run_dir / "report.html"
    path.write_text(''.join(parts), encoding="utf-8")
    return path
