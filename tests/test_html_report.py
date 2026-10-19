import copy
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from macro.reporting.html_report import diagnostic_notes, render_report
from macro.shared.io import write_json, write_jsonl
from macro.reporting.summary import summarize
from macro.shared.benchmark_policy import evaluate_case
from tests.fixtures import CONFIG, fixture


class Markup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.ids, self.targets, self.scripts = [], [], 0
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.targets.append(attrs["href"][1:])
        self.scripts += tag == "script"


class HtmlReportTests(unittest.TestCase):
    def populate(self, folder):
        case = fixture()
        case["candidate_pool"][0]["title"] = '<script>alert("recipe")</script>'
        write_json(folder / "manifest.json", {"mode": "live", "config": CONFIG})
        write_jsonl(folder / "cases.snapshot.jsonl", [case])
        write_jsonl(folder / "references.snapshot.private.jsonl", [{"case_id": "fixture", **evaluate_case(case)}])
        for name in ["roles", "evaluations", "calls"]:
            (folder / name).mkdir()
        assessment = {"findings": [
            {"candidate": "A", "feasible": True, "violations": [], "nutrition_score": .25,
             "evidence": ["/candidate_pool/0/nutrition_score"]},
            {"candidate": "B", "feasible": False, "violations": ["duration"], "nutrition_score": .875,
             "evidence": ["/candidate_pool/1/duration_minutes"]}],
            "nutrition_comparison": "A", "rationale": '<img src=x onerror="alert(1)"> rationale'}
        write_json(folder / "roles" / "attribute.json", {"case_id": "fixture", "order": "original",
                   "role": "attribute", "attempt": 1, "status": "ok", "elapsed_seconds": 1.2,
                   "assessment": assessment, "raw": json.dumps(assessment),
                   "system_prompt": "Instructions", "user_prompt": json.dumps(case)})
        write_json(folder / "roles" / "failure.json", {"case_id": "fixture", "order": "reversed",
                   "role": "single", "attempt": 1, "status": "technical_failure", "assessment": None,
                   "raw": "<script>failed raw</script>", "error_type": "AssessmentValidationError",
                   "validation_errors": [{"code": "missing_candidate", "message": "B is missing"}]})
        write_json(folder / "evaluations" / "panel.json", {"case_id": "fixture", "order": "original",
                   "system": "specialists", "status": "ok", "decision": "A", "attributes": [],
                   "reported_comparisons": {"nutrition_comparison": "A"},
                   "derived_comparisons": {"nutrition_comparison": "B"},
                   "comparison_diagnostics": [{"criterion": "nutrition", "reported": "A", "derived": "B"}]})
        return case

    def test_automatic_summary_html_handles_partial_run_and_escapes_content(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.populate(folder)
            with patch("socket.socket", side_effect=AssertionError("No network allowed")):
                summarize(folder)
            html = (folder / "report.html").read_text(encoding="utf-8")
            parsed = Markup(html)
            self.assertEqual(parsed.scripts, 1)  # Only the report's own evidence-link handler.
            self.assertIn("&lt;script&gt;", html)
            self.assertNotIn('<img src=x', html)
            self.assertIn("nutrition_comparison: reported A", html)
            self.assertIn("B is missing", html)
            self.assertIn("No saved assessment", html)
            self.assertIn("repeated unresolved outcomes can be stable and incorrect", html)
            self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
            self.assertTrue(set(parsed.targets) <= set(parsed.ids))
            self.assertIn("roles/attribute.json", html)
            self.assertIn("Reversed candidate order", html)
            self.assertIn("Raw response · formatted for reading", html)
            self.assertIn("Coordinator comparison warnings", html)
            self.assertIn("Coordinator calculated", html)

    def test_report_only_generation_preserves_saved_files_and_diagnostics_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            case = self.populate(folder)
            summarize(folder)
            before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file() and p.name != "report.html"}
            render_report(folder)
            self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
            assessment = {"findings": [{"candidate": "A", "feasible": False, "violations": ["duration"],
                                        "nutrition_score": .25},
                                       {"candidate": "B", "nutrition_score": .25}],
                          "nutrition_comparison": "B"}
            unchanged = copy.deepcopy(assessment)
            notes = diagnostic_notes(assessment, case)
            self.assertEqual(len(notes), 2)
            self.assertEqual(assessment, unchanged)


if __name__ == "__main__":
    unittest.main()
