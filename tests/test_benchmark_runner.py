"""Benchmark integration checks. Fixtures are not evidence of model accuracy."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openai.types.chat import ChatCompletion
from openai.resources.chat.completions import Completions

from macro.ai_agents.agents import LiveProvider
from macro.ai_agents.benchmark_schemas import aggregate
from macro.ai_agents.prompts import visible_case
from macro.ai_agents.schemas import validate_assessment, AssessmentValidationError
from macro.evaluation.runner import _run, run, load_inputs, experiment_plan, CallRecorder
from macro.evaluation.metrics import compute
from macro.shared.benchmark_policy import evaluate_case
from macro.shared.io import read_json
from tests.fixtures import as_wire

ROOT = Path(__file__).resolve().parents[1]
CONFIG = read_json(ROOT / "configs/deepseek-pilot.json")


def fixture():
    return {"case_id": "benchmark-fixture", "request": "Prefer garlic, nutrition then speed then preference; no hard limit.",
            "profile": {"preferred_ingredients": ["garlic"], "excluded_ingredients": [],
                        "hard_max_duration_minutes": None, "objectives": ["preference", "nutrition", "speed"],
                        "priorities": ["nutrition", "speed", "preference"]},
            "candidate_pool": [
                {"id": "r1", "duration_minutes": 20.0, "nutrition_score": .5,
                 "nutrition_metric": "hummus_normalized_fsa", "canonical_ingredients": ["garlic"]},
                {"id": "r2", "duration_minutes": 10.0, "nutrition_score": .5,
                 "nutrition_metric": "hummus_normalized_fsa", "canonical_ingredients": []}],
            "recommendations": {"A": {"recipe_id": "r1", "explanation": "20 minutes, garlic, FSA 0.5"},
                                "B": {"recipe_id": "r2", "explanation": "10 minutes, no groups, FSA 0.5"}}}


class ReferenceFixtureProvider:
    """Test-only oracle payloads exercise persistence, never model performance."""
    def assess(self, role, evidence, tag, feedback=None):
        ref = evaluate_case({"case_id": "fixture", **evidence})
        profile = evidence["profile"]
        preferences, attributes, explanations = [], [], []
        for slot in ["A", "B"]:
            finding = ref["candidates"][slot]
            recipe = next(r for r in evidence["candidate_pool"] if r["id"] == finding["recipe_id"])
            preferences.append({"candidate": slot, "preference_score": finding["objective_scores"].get("preference"), "evidence": ["/profile"]})
            attributes.append({"candidate": slot, "feasible": finding["feasible"], "violations": finding["violations"],
                               "nutrition_score": recipe["nutrition_score"], "speed_score": -recipe["duration_minutes"], "evidence": ["/candidate_pool"]})
            explanations.append({"candidate": slot, "supported": True, "relevant_tradeoffs_disclosed": True,
                                 "issues": [], "evidence": [f"/recommendations/{slot}/explanation"]})
        from macro.shared.policy import compare
        attr_comparisons = {o + "_comparison": compare(attributes[0][o + "_score"], attributes[1][o + "_score"]) for o in ["nutrition", "speed"]}
        pref_fields = {"objectives": profile["objectives"], "priorities": profile["priorities"],
                       "preference_comparison": ref["objective_comparisons"].get("preference")}
        if role == "single":
            value = {"preferences": preferences, "attributes": attributes, "explanations": explanations,
                     **pref_fields, **attr_comparisons, "decision": ref["verdict"]}
        elif role == "preference":
            value = {"findings": preferences, **pref_fields}
        elif role == "attribute":
            value = {"findings": attributes, **attr_comparisons}
        else:
            value = {"findings": explanations}
        value["rationale"] = "OFFLINE reference fixture; not a model judgment."
        wire = as_wire(role, value)
        return {"status": "ok", "assessment": validate_assessment(role, wire, evidence), "raw": json.dumps(wire),
                "provider": "offline_reference_fixture", "tool_calls": []}


class BenchmarkIntegrationTests(unittest.TestCase):
    def records(self, case):
        return {r: ReferenceFixtureProvider().assess(r, visible_case(case), "fixture") for r in ["single", "preference", "attribute", "explanation"]}

    def test_policy_speed_priority_and_no_priority(self):
        case = fixture()
        self.assertEqual(aggregate(self.records(case))["decision"], "B")
        case["profile"]["priorities"] = None
        self.assertEqual(aggregate(self.records(case))["decision"], "insufficient_information")
        case["profile"]["objectives"] = ["nutrition"]
        case["profile"]["preferred_ingredients"] = []
        self.assertEqual(aggregate(self.records(case))["decision"], "tie")
        case["profile"]["hard_max_duration_minutes"] = 10
        self.assertEqual(aggregate(self.records(case))["decision"], "B")
        case["profile"]["hard_max_duration_minutes"] = 5
        self.assertEqual(aggregate(self.records(case))["decision"], "both_violate")

    def test_uses_reported_scores_and_rejects_bad_coverage(self):
        records = self.records(fixture())
        records["attribute"]["assessment"]["findings"][0]["nutrition_score"] = 1.0
        result = aggregate(records)
        self.assertEqual(result["decision"], "A")
        self.assertEqual(result["comparison_diagnostics"][0]["criterion"], "nutrition")
        records["explanation"]["assessment"]["findings"].pop()
        self.assertEqual(aggregate(records)["status"], "technical_failure")

    def test_nullable_scores_priorities_and_pointers(self):
        case = fixture()
        evidence = visible_case(case)
        raw = json.loads(self.records(case)["preference"]["raw"])
        raw["priorities"] = ["nutrition"]
        with self.assertRaises(AssessmentValidationError):
            validate_assessment("preference", raw, evidence)
        raw["priorities"] = None
        raw["findings"]["A"]["preference_score"] = None
        with self.assertRaises(AssessmentValidationError):
            validate_assessment("preference", raw, evidence)
        raw = json.loads(self.records(case)["attribute"]["raw"])
        raw["findings"]["A"]["evidence"] = ["/private/verdict"]
        with self.assertRaises(AssessmentValidationError):
            validate_assessment("attribute", raw, evidence)

    def test_deepseek_sdk_all_roles_without_network(self):
        case = fixture()
        case["private_reference"] = "SECRET_REFERENCE"
        evidence = visible_case(case)
        for role, record in self.records(case).items():
            response = ChatCompletion.model_validate({"id": "mock", "object": "chat.completion", "created": 0,
                "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": record["raw"]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                with patch.object(Completions, "create", return_value=response) as create, patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), patch("macro.ai_agents.agents.api_key", return_value="offline-key"):
                    saved = LiveProvider(CONFIG, CallRecorder(temp, 6)).assess(role, evidence, "fixture_attempt-01")
                self.assertEqual(saved["schema_version"], "benchmark-assessment-v1")
                self.assertEqual(create.call_args.kwargs["response_format"], {"type": "json_object"})
                self.assertEqual(create.call_args.kwargs["extra_body"], {"thinking": {"type": "disabled"}})
                messages = json.dumps(create.call_args.kwargs["messages"])
                self.assertNotIn("SECRET_REFERENCE", messages)
                self.assertIn("benchmark-policy-v1", messages)
                self.assertNotIn("Duration is a hard limit only", messages)

    def test_full_dev_pipeline_resume_identity_and_reports(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()), patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            with patch("macro.evaluation.runner.Path", wraps=Path) as paths:
                # Redirect only results output, retaining real benchmark input paths.
                paths.side_effect = lambda value: Path(temp) / "results" if value == "results" else Path(value)
                folder = _run(ROOT / "data/benchmark-v2", CONFIG, lambda _: ReferenceFixtureProvider(), "offline",
                              limit=120, run_id="benchmark-dev-integration", max_calls=0, split="dev")
                summary = read_json(folder / "summary.json")
                self.assertFalse(summary["is_model_performance"])
                self.assertEqual(summary["costs"]["model_calls"], 0)
                for metric in summary["metrics"].values():
                    self.assertEqual(metric["evaluation_coverage"]["correct"], 240)
                    self.assertEqual(metric["overall_accuracy"]["rate"], 1)
                    self.assertEqual(metric["macro_category_accuracy"], 1)
                self.assertIn("both_violate", (folder / "report.md").read_text(encoding="utf-8"))
                self.assertIn("negative minutes", (folder / "report.html").read_text(encoding="utf-8"))
                _run(ROOT / "data/benchmark-v2", CONFIG, lambda _: ReferenceFixtureProvider(), "offline",
                     limit=120, run_id="benchmark-dev-integration", max_calls=0, split="dev")
                with self.assertRaisesRegex(ValueError, "Resume"):
                    _run(ROOT / "data/benchmark-v2", {**CONFIG, "max_tokens": 4000}, lambda _: ReferenceFixtureProvider(), "offline",
                         limit=120, run_id="benchmark-dev-integration", max_calls=0, split="dev")

    def test_test_split_preview_and_execution_guard(self):
        plan = experiment_plan(ROOT / "data/benchmark-v2", 400, CONFIG, split="test")
        self.assertEqual(plan["total_initial_calls"], 3200)
        self.assertEqual(plan["maximum_with_all_retries_and_tool_rounds"], 19200)
        with patch("macro.evaluation.runner.api_key", side_effect=AssertionError("Do not read credentials")):
            with self.assertRaisesRegex(ValueError, "Final test execution is disabled"):
                run(ROOT / "data/benchmark-v2", CONFIG, limit=400, split="test")

    def test_missing_evaluations_count_against_all_categories(self):
        cases, refs = load_inputs(ROOT / "data/benchmark-v2", 120, "dev")
        report = compute(cases, refs, {})
        for metric in report.values():
            self.assertEqual(metric["overall_accuracy"], {"correct": 0, "total": 240, "rate": 0})
            self.assertEqual(metric["diagnostic_counts"], {"missing": 240})
            self.assertEqual(len(metric["accuracy_by_type"]), 5)


if __name__ == "__main__":
    unittest.main()
