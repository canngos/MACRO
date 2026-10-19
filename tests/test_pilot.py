import copy
import contextlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.evaluate_case_generation.source_audit import normalize
from macro.cli import main
from macro.shared.io import read_json, write_json, write_jsonl
from macro.ai_agents.agents import LiveProvider
from macro.ai_agents.tools import calculate
from macro.coordinator.aggregation import aggregate
from macro.evaluation.metrics import compute
from macro.shared.policy import canonical_matches, canonical_decision, findings, ingredient_head, swapped
from macro.ai_agents.prompts import visible_case
from macro.evaluation.runner import BudgetExceeded, CallRecorder, run, source_code_hashes
from tests.fixtures import OfflineProvider, run_fixture
from macro.ai_agents.schemas import validate_assessment


def fixture():
    # Independent, hand-specified inputs. A is feasible; B exceeds 30 minutes.
    return {"case_id": "fixture", "profile": {"preferred_ingredients": ["garlic", "onion"],
        "excluded_ingredients": ["mushroom"], "max_duration_minutes": 30.0, "priority": "preference_first"},
        "request": "No mushrooms, at most 30 minutes, preference first.",
        "candidate_pool": [
            {"id": "1", "title": "A", "duration_minutes": 30.0, "canonical_ingredients": ["garlic", "onion"], "ingredient_names": ["garlic", "onion"], "nutrition_score": .25},
            {"id": "2", "title": "B", "duration_minutes": 45.0, "canonical_ingredients": ["garlic"], "ingredient_names": ["garlic"], "nutrition_score": .875}],
        "recommendations": {"A": {"recipe_id": "1", "explanation": "30 minutes, garlic and onion, score 0.25"},
                            "B": {"recipe_id": "2", "explanation": "45 minutes, garlic, score 0.875"}}}


CONFIG = {"model": "gpt-5-nano", "reasoning_effort": "low", "max_completion_tokens": 3500,
          "timeout_seconds": 60, "max_attempts": 2, "max_tool_rounds": 2, "pricing": None}


class ReferenceTests(unittest.TestCase):
    def test_boundary_duration_and_precedence(self):
        r = findings(fixture())
        self.assertEqual(r["decision"], "A")
        self.assertEqual(r["candidates"]["A"]["violations"], [])
        self.assertEqual(r["candidates"]["B"]["violations"], ["duration"])

    def test_exclusion_cannot_be_compensated(self):
        c = fixture()
        c["candidate_pool"][0]["canonical_ingredients"].append("mushroom")
        self.assertEqual(findings(c)["decision"], "neither_feasible")
        c["candidate_pool"][1]["duration_minutes"] = 20
        self.assertEqual(findings(c)["decision"], "B")

    def test_dominance_tradeoff_tie(self):
        c = fixture()
        c["candidate_pool"][1]["duration_minutes"] = 20
        c["candidate_pool"][0]["nutrition_score"] = .875
        self.assertEqual(findings(c)["decision"], "A")
        c["candidate_pool"][0]["nutrition_score"] = .25
        self.assertEqual(findings(c)["case_type"], "tradeoff")
        self.assertEqual(findings(c)["decision"], "A")
        c["profile"]["priority"] = "nutrition_first"
        self.assertEqual(findings(c)["decision"], "B")
        c["profile"]["priority"] = "unspecified"
        self.assertEqual(findings(c)["decision"], "unresolved")
        c["candidate_pool"][1]["canonical_ingredients"].append("onion")
        c["candidate_pool"][1]["nutrition_score"] = .25 + 5e-10
        self.assertEqual(findings(c)["decision"], "tie")

    def test_aliases_and_mapping_bounds(self):
        self.assertEqual(ingredient_head("finely chopped large red onion, peeled"), "red onion")
        self.assertEqual(canonical_matches(["olive oil", "black olives", "tomato sauce", "tomatoes"]), ["olive", "tomato"])

    def test_swap_identity(self):
        c = fixture()
        s = swapped(c)
        self.assertEqual(findings(s)["decision"], "B")
        self.assertEqual(canonical_decision(c, "A"), canonical_decision(s, "B"))
        self.assertEqual(s["recommendations"]["B"]["explanation"], c["recommendations"]["A"]["explanation"])
        self.assertEqual(swapped(s), c)

    def test_original_ingredients_and_malformed_source(self):
        row = {"recipe_id": "17", "title": "Garlic soup", "duration": "30", "fsa_score": "0.5",
               "normalization_comment": "", "ingredients": "{'main': [('garlic cloves', '2'), ('water', '1 cup')]}",
               "ingredient_food_kg_names": "['tomato', 'olive']", "recipe_url": "https://example.invalid/17"}
        self.assertEqual(normalize(row, 1)["canonical_ingredients"], ["garlic"])
        row["ingredients"] = "{'main': [('garlic powder', '2')]}"
        with self.assertRaisesRegex(ValueError, "unmapped_curated"):
            normalize(row, 1)
        row["ingredients"] = "{'main': [('', '2')]}"
        with self.assertRaisesRegex(ValueError, "invalid_raw"):
            normalize(row, 1)
        row["title"] = "------------"
        with self.assertRaisesRegex(ValueError, "missing_identity"):
            normalize(row, 1)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.evidence = visible_case(fixture())
        self.records = {role: OfflineProvider().assess(role, self.evidence, "fixture") for role in ["single", "preference", "attribute", "explanation"]}

    def test_aggregation_and_missing_roles(self):
        self.assertEqual(aggregate(self.records)["decision"], "A")
        self.assertEqual(aggregate({})["status"], "technical_failure")
        self.records["attribute"]["assessment"]["findings"][0]["feasible"] = False
        self.records["attribute"]["assessment"]["findings"][0]["violations"] = ["excluded:mushroom"]
        self.assertEqual(aggregate(self.records)["decision"], "neither_feasible")
        for f in self.records["attribute"]["assessment"]["findings"]:
            f.update(feasible=True, violations=[], nutrition_score=.25)
        self.records["attribute"]["assessment"]["nutrition_comparison"] = "equal"
        for f in self.records["preference"]["assessment"]["findings"]:
            f["preference_score"] = .5
        self.records["preference"]["assessment"]["preference_comparison"] = "equal"
        self.assertEqual(aggregate(self.records)["decision"], "tie")
        self.records["preference"]["assessment"]["findings"][0]["preference_score"] = 1
        self.records["preference"]["assessment"].update(preference_comparison="A", priority="unspecified")
        self.records["attribute"]["assessment"]["findings"][1]["nutrition_score"] = .875
        self.records["attribute"]["assessment"]["nutrition_comparison"] = "B"
        self.assertEqual(aggregate(self.records)["decision"], "unresolved")

    def test_conflicting_role_summary(self):
        self.records["preference"]["assessment"]["preference_comparison"] = "B"
        before = copy.deepcopy(self.records)
        result = aggregate(self.records)
        self.assertEqual((result["decision"], result["status"]), ("A", "ok"))
        self.assertEqual(result["comparison_diagnostics"][0]["criterion"], "preference")
        self.assertEqual(result["reported_comparisons"]["preference_comparison"], "B")
        self.assertEqual(result["derived_comparisons"]["preference_comparison"], "A")
        self.assertEqual(self.records, before)

    def test_numeric_aggregation_dominance_priorities_and_no_explanation_vote(self):
        pref = self.records["preference"]["assessment"]
        attr = self.records["attribute"]["assessment"]
        for f in attr["findings"]:
            f.update(feasible=True, violations=[])
        # A has greater preference, B greater nutrition. Deliberately wrong labels.
        pref["preference_comparison"] = "B"
        attr["nutrition_comparison"] = "A"
        for priority, expected in [("preference_first", "A"), ("nutrition_first", "B"), ("unspecified", "unresolved")]:
            pref["priority"] = priority
            self.records["explanation"]["assessment"]["findings"][0]["supported"] = False
            result = aggregate(self.records)
            self.assertEqual((result["status"], result["decision"]), ("ok", expected))
            self.assertEqual(len(result["comparison_diagnostics"]), 2)
        attr["findings"][1]["nutrition_score"] = .25 + 5e-10
        self.assertEqual(aggregate(self.records)["decision"], "A")  # Dominance, including tolerance.
        pref["findings"][1]["preference_score"] = 1.0
        self.assertEqual(aggregate(self.records)["decision"], "tie")

    def test_numeric_aggregation_keeps_wrong_scores_and_rejects_invalid_records(self):
        # The coordinator has no case/reference access and must not repair wrong predictions.
        for f in self.records["attribute"]["assessment"]["findings"]:
            f.update(feasible=True, violations=[], nutrition_score=.25)
        p = self.records["preference"]["assessment"]["findings"]
        p[0]["preference_score"], p[1]["preference_score"] = 0.0, 1.0
        self.assertEqual(aggregate(self.records)["decision"], "B")
        for mutation in ["missing", "duplicate", "nonfinite", "contradictory_feasibility"]:
            records = copy.deepcopy(self.records)
            if mutation == "missing":
                records["explanation"]["assessment"] = None
            elif mutation == "duplicate":
                records["preference"]["assessment"]["findings"][1]["candidate"] = "A"
            elif mutation == "nonfinite":
                records["attribute"]["assessment"]["findings"][0]["nutrition_score"] = float("nan")
            else:
                records["attribute"]["assessment"]["findings"][0]["violations"] = ["duration"]
            result = aggregate(records)
            self.assertEqual((result["status"], result["decision"]), ("technical_failure", None))

    def test_invalid_output_and_leakage(self):
        raw = copy.deepcopy(self.records["single"]["assessment"])
        raw["attributes"][0]["evidence"] = ["/references/winner"]
        with self.assertRaises(ValueError):
            validate_assessment("single", raw, self.evidence)
        raw = copy.deepcopy(self.records["single"]["assessment"])
        raw["attributes"][1]["candidate"] = "A"
        with self.assertRaises(ValueError):
            validate_assessment("single", raw, self.evidence)
        c = fixture()
        c.update({"case_type": "constraint", "reference": "A", "difficulty": "near"})
        self.assertEqual(set(visible_case(c)), {"profile", "request", "candidate_pool", "recommendations"})
        self.assertNotIn("fixture", self.records["single"]["user_prompt"])

    def test_calculator(self):
        self.assertEqual(calculate("divide", [1, 2]), {"value": .5})
        self.assertEqual(calculate("subtract", [.875, .25]), {"value": .625})
        self.assertIn("error", calculate("divide", [1, 0]))
        self.assertIn("error", calculate("sum", [float("nan")]))


class MetricsTests(unittest.TestCase):
    def test_comparison_warnings_are_counted_without_invalidating_decisions(self):
        c = fixture()
        ref = {"case_id": c["case_id"], **findings(c)}
        results = {}
        for system in ["single", "specialists"]:
            for order, decision in [("original", "A"), ("reversed", "B")]:
                results[c["case_id"], order, system] = {"status": "ok", "decision": decision,
                    "comparison_diagnostics": [{"criterion": "nutrition"}], "attributes": []}
        metrics = compute([c], [ref], results)
        for metric in metrics.values():
            self.assertEqual(metric["accuracy_by_type"]["constraint"]["correct"], 2)
            self.assertEqual(metric["comparison_consistency"]["evaluations_with_warnings"], 2)
            self.assertEqual(metric["comparison_consistency"]["warnings_by_criterion"], {"nutrition": 2})

    def test_unresolved_is_distinct_from_failure_and_wrong_priority(self):
        c = fixture()
        c["profile"]["priority"] = "unspecified"
        c["candidate_pool"][1]["duration_minutes"] = 20
        ref = {"case_id": "fixture", **findings(c)}
        results = {(c["case_id"], order, "single"): {"status": "ok", "decision": "unresolved", "attributes": []}
                   for order in ["original", "reversed"]}
        m = compute([c], [ref], results)["single"]
        self.assertEqual(m["accuracy_by_type"]["tradeoff"]["rate"], 1)
        self.assertEqual(m["candidate_order_stability"]["rate"], 1)
        results[(c["case_id"], "original", "single")]["status"] = "inconsistent_findings"
        self.assertEqual(compute([c], [ref], results)["single"]["accuracy_by_type"]["tradeoff"]["rate"], .5)
        results[(c["case_id"], "original", "single")] = {"status": "technical_failure", "decision": None}
        self.assertEqual(compute([c], [ref], results)["single"]["evaluation_coverage"]["rate"], .5)

    def test_hand_calculated_errors_and_missing_results(self):
        c1, c2 = fixture(), fixture()
        c2["case_id"] = "second"
        refs = [
            {"case_id": "fixture", "case_type": "constraint", "decision": "A", "candidates": {"A": {"feasible": True}, "B": {"feasible": False}}},
            {"case_id": "second", "case_type": "dominance", "decision": "A", "candidates": {"A": {"feasible": True}, "B": {"feasible": True}}}]
        results = {
            ("fixture", "original", "single"): {"status": "ok", "decision": "A", "attributes": [{"candidate": "A", "feasible": True}, {"candidate": "B", "feasible": False}]},
            ("fixture", "reversed", "single"): {"status": "ok", "decision": "A", "attributes": [{"candidate": "A", "feasible": False}, {"candidate": "B", "feasible": False}]},
            ("second", "reversed", "single"): {"status": "ok", "decision": "A", "attributes": [{"candidate": "A", "feasible": True}, {"candidate": "B", "feasible": True}]}}
        m = compute([c1, c2], refs, results)["single"]
        self.assertEqual(m["evaluation_coverage"]["rate"], .75)
        self.assertEqual(m["accuracy_by_type"]["constraint"]["rate"], .5)
        self.assertEqual(m["accuracy_by_type"]["dominance"]["rate"], 0)
        self.assertEqual(m["constraint_detection"]["tp"], 2)
        self.assertEqual(m["constraint_detection"]["fp"], 1)
        self.assertEqual(m["constraint_detection"]["precision"], 2/3)
        self.assertEqual(m["constraint_detection"]["recall"], 1)
        self.assertEqual(m["candidate_order_stability"]["rate"], 0)
        self.assertEqual(m["constraint_detection"]["observed_flags"], 6)


class RunnerTests(unittest.TestCase):
    def test_resume_fingerprint_covers_nested_modules_without_filename_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "macro"
            for relative in ["__init__.py", "evaluation/runner.py", "ai_agents/__init__.py", "coordinator/__init__.py"]:
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# initial\n", encoding="utf-8")
            with patch("macro.evaluation.runner.__file__", str(package / "evaluation/runner.py")):
                before = source_code_hashes()
                self.assertEqual(len(before), 4)
                self.assertIn("ai_agents/__init__.py", before)
                self.assertIn("coordinator/__init__.py", before)
                (package / "coordinator/__init__.py").write_text("# changed policy module\n", encoding="utf-8")
                after = source_code_hashes()
                self.assertNotEqual(before, after)
                self.assertEqual(before["ai_agents/__init__.py"], after["ai_agents/__init__.py"])

    def test_user_run_requires_acknowledgement_and_uses_real_provider(self):
        with patch("sys.argv", ["macro", "run"]), patch("macro.evaluation.runner.run") as mocked, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 2)
            mocked.assert_not_called()
        with patch("sys.argv", ["macro", "run", "--allow-paid-api", "--limit", "1"]), patch("macro.evaluation.runner.run") as mocked:
            main()
            self.assertEqual(mocked.call_args.args[2], 1)
            mocked.assert_called_once()
        with tempfile.TemporaryDirectory() as empty, patch("macro.shared.config.Path.cwd", return_value=Path(empty)), patch.dict(os.environ, {}, clear=True), patch("macro.evaluation.runner._run") as mocked:
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                run("data", CONFIG)
            mocked.assert_not_called()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "not-used-by-mocked-runner"}), patch("macro.evaluation.runner._run") as mocked:
            run("data", CONFIG)
            self.assertEqual(mocked.call_args.args[3], "live")
            with tempfile.TemporaryDirectory() as folder:
                self.assertIsInstance(mocked.call_args.args[2](CallRecorder(folder, 3)), LiveProvider)

    def test_offline_network_blocked_resume_and_budget(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                write_jsonl("data/cases.jsonl", [fixture()])
                write_jsonl("data/references.private.jsonl", [{"case_id": "fixture", **findings(fixture())}])
                with patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")), patch.dict(os.environ, {}, clear=True):
                    path = run_fixture("data", CONFIG, limit=1, run_id="offline-test")
                    before = {p.name: p.read_bytes() for p in (path / "roles").glob("*.json")}
                    with patch.object(OfflineProvider, "assess", side_effect=AssertionError("successful role repeated")):
                        run_fixture("data", CONFIG, limit=1, run_id="offline-test")
                    self.assertEqual(before, {p.name: p.read_bytes() for p in (path / "roles").glob("*.json")})
                    self.assertEqual(read_json(path / "summary.json")["costs"]["model_calls"], 0)
                recorder = CallRecorder(path / "calls", 1)
                recorder.begin("x", "single", [])
                with self.assertRaises(BudgetExceeded):
                    recorder.begin("x", "single", [])
                with self.assertRaisesRegex(ValueError, "Interrupted"):
                    run_fixture("data", CONFIG, limit=1, run_id="offline-test")
                for path in recorder.folder.glob("*.json"):
                    row = read_json(path)
                    recorder.end(row["call_id"], {"status": "complete"})
                recorder = CallRecorder(path.parent, 3)
                orphan = recorder.begin("fixture_original_attempt-02", "single", [])
                recorder.end(orphan, {"status": "complete", "usage": {"total_tokens": 150}})
                with self.assertRaisesRegex(ValueError, "Interrupted"):
                    run_fixture("data", CONFIG, limit=1, run_id="offline-test")
                with self.assertRaises(BudgetExceeded):
                    recorder.reserve(3)
            finally:
                os.chdir(previous)

    def test_real_ag2_adapter_mocked_sdk_and_tool_loop(self):
        # Exercise installed AG2/SDK serialization with fake responses and networking blocked.
        from openai.types.chat import ChatCompletion
        from openai.resources.chat.completions import Completions
        evidence = visible_case(fixture())
        raw = OfflineProvider().assess("single", evidence, "x")["raw"]
        def response(message, finish):
            return ChatCompletion.model_validate({"id": "mock", "object": "chat.completion", "created": 0, "model": "gpt-5-nano", "choices": [{"index": 0, "finish_reason": finish, "message": message}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        responses = [response({"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "calculate", "arguments": '{"operation":"divide","values":[1,2]}'}}]}, "tool_calls"),
                     response({"role": "assistant", "content": raw}, "stop")]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-placeholder"}), patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")), patch.object(Completions, "create", side_effect=responses) as mocked:
            record = LiveProvider(CONFIG, CallRecorder(folder, 3)).assess("single", evidence, "x")
            self.assertEqual(record["assessment"]["decision"], "A")
            self.assertEqual(record["tool_calls"][0]["result"], {"value": .5})
            self.assertEqual(mocked.call_count, 2)
            kwargs = mocked.call_args.kwargs
            self.assertEqual(kwargs["response_format"]["type"], "json_schema")
            self.assertNotIn("temperature", kwargs)
            self.assertEqual(kwargs["max_completion_tokens"], 3500)
            self.assertEqual(kwargs["messages"][-1]["role"], "tool")
            calls = [read_json(p) for p in Path(folder).glob("*.json")]
            self.assertEqual(sum(c["usage"]["total_tokens"] for c in calls), 300)
            self.assertEqual(sum(len(c.get("executed_tools", [])) for c in calls), 1)
            self.assertNotIn("offline-test-placeholder", ''.join(p.read_text() for p in Path(folder).glob("*.json")))


if __name__ == "__main__":
    unittest.main()
