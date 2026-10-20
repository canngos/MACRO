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

from macro.cli import main
from macro.shared.io import read_json, write_json, write_jsonl
from macro.ai_agents.agents import LiveProvider
from macro.ai_agents.tools import calculate
from macro.coordinator.aggregation import aggregate
from macro.evaluation.metrics import compute
from macro.shared.benchmark_policy import evaluate_case
from macro.shared.comparison import canonical_decision, swapped
from macro.ai_agents.prompts import visible_case
from macro.evaluation.runner import BudgetExceeded, CallRecorder, run, source_code_hashes
from tests.fixtures import OfflineProvider, run_fixture, fixture, CONFIG, write_fixture_package
from macro.ai_agents.schemas import validate_assessment


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.evidence = visible_case(fixture())
        self.records = {role: OfflineProvider().assess(role, self.evidence, "fixture") for role in ["single", "preference", "attribute", "explanation"]}

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
        ref = {"case_id": c["case_id"], **evaluate_case(c)}
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
        c["profile"]["priorities"] = None
        c["candidate_pool"][1]["duration_minutes"] = 20
        ref = {"case_id": "fixture", **evaluate_case(c)}
        results = {(c["case_id"], order, "single"): {"status": "ok", "decision": "insufficient_information", "attributes": []}
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

    @patch("macro.shared.config.dotenv_values", return_value={})
    def test_user_run_requires_acknowledgement_and_uses_real_provider(self, _dotenv):
        with patch("sys.argv", ["macro", "run"]), patch("macro.evaluation.runner.run") as mocked, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 2)
            mocked.assert_not_called()
        with patch("sys.argv", ["macro", "run", "--allow-paid-api", "--limit", "1", "--max-calls", "48"]), patch("macro.evaluation.runner.run") as mocked:
            main()
            self.assertEqual(mocked.call_args.args[2], 1)
            mocked.assert_called_once()
        with patch.dict(os.environ, {}, clear=True), patch("macro.evaluation.runner._run") as mocked:
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
                write_fixture_package("data")
                with patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")), patch.dict(os.environ, {}, clear=True):
                    path = run_fixture("data/test", CONFIG, limit=1, run_id="offline-test")
                    before = {p.name: p.read_bytes() for p in (path / "roles").glob("*.json")}
                    with patch.object(OfflineProvider, "assess", side_effect=AssertionError("successful role repeated")):
                        run_fixture("data/test", CONFIG, limit=1, run_id="offline-test")
                    self.assertEqual(before, {p.name: p.read_bytes() for p in (path / "roles").glob("*.json")})
                    self.assertEqual(read_json(path / "summary.json")["costs"]["model_calls"], 0)
                recorder = CallRecorder(path / "calls", 1)
                recorder.begin("x", "single", [])
                with self.assertRaises(BudgetExceeded):
                    recorder.begin("x", "single", [])
                with self.assertRaisesRegex(ValueError, "Interrupted"):
                    run_fixture("data/test", CONFIG, limit=1, run_id="offline-test")
                for path in recorder.folder.glob("*.json"):
                    row = read_json(path)
                    recorder.end(row["call_id"], {"status": "complete"})
                recorder = CallRecorder(path.parent, 3)
                orphan = recorder.begin("fixture_original_attempt-02", "single", [])
                recorder.end(orphan, {"status": "complete", "usage": {"total_tokens": 150}})
                with self.assertRaisesRegex(ValueError, "Interrupted"):
                    run_fixture("data/test", CONFIG, limit=1, run_id="offline-test")
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
