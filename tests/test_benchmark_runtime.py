"""Internal benchmark checks; never a user-facing offline evaluation mode."""
import contextlib
import copy
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.ai_agents.schemas import response_schema, validate_assessment, AssessmentValidationError
from macro.ai_agents.prompts import visible_case, prompt
from macro.ai_agents.agents import LiveProvider
from macro.coordinator.aggregation import guard_single
from macro.coordinator.aggregation import aggregate
from macro.evaluation.runner import _run, CallRecorder, experiment_plan
from macro.evaluation.metrics import compute
from macro.evaluate_case_generation.benchmark import verify_saved
from macro.shared.io import read_json, read_jsonl, file_hash
from macro.shared.comparison import swapped
from tests.fixtures import as_wire, completion, speed_fixture as fixture, OfflineProvider as BenchmarkFixtureProvider

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'data/benchmark-v2'
CONFIG = read_json(ROOT / 'configs/benchmark-judges.json')


class BenchmarkRuntimeTests(unittest.TestCase):
    def records(self, case):
        return {r: BenchmarkFixtureProvider().assess(r, visible_case(case), 'test') for r in ('single', 'preference', 'attribute', 'explanation')}

    def test_speed_priority_inactive_speed_and_unresolved(self):
        c = fixture()
        self.assertEqual(aggregate(self.records(c), c)['decision'], 'A')
        c['profile']['priorities'] = None
        self.assertEqual(aggregate(self.records(c), c)['decision'], 'insufficient_information')
        c['profile']['objectives'] = ['preference', 'nutrition']
        self.assertEqual(aggregate(self.records(c), c)['decision'], 'B')
        c['candidate_pool'][0]['nutrition_score'] = .75
        self.assertEqual(aggregate(self.records(c), c)['decision'], 'tie')
        c['profile']['objectives'].append('speed')
        self.assertEqual(aggregate(self.records(c), c)['decision'], 'A')
        self.assertEqual(aggregate(self.records(swapped(c)), swapped(c))['decision'], 'B')

    def test_verified_failures_override_both_systems_but_raw_flags_survive(self):
        c = fixture()
        c['profile']['hard_max_duration_minutes'] = 15.
        records = self.records(c)
        for a in records['attribute']['assessment']['findings']:
            a['feasible'], a['violations'] = True, []
        records['preference']['assessment']['findings'][0]['preference_score'] = 0.
        records['attribute']['assessment']['findings'][0]['duration_minutes'] = 25.
        panel = aggregate(records, c)
        self.assertEqual(panel['raw_decision'], 'B')
        self.assertEqual(panel['decision'], 'A')
        self.assertTrue(panel['attributes'][1]['feasible'])
        single = guard_single(dict(status='ok', decision='B', attributes=panel['attributes']), c)
        self.assertEqual(single['raw_decision'], 'B')
        self.assertEqual(single['decision'], 'A')
        c['profile']['hard_max_duration_minutes'] = 5.
        self.assertEqual(guard_single(dict(status='ok', decision='A'), c)['decision'], 'both_violate')
        self.assertEqual(aggregate(records, c)['decision'], 'both_violate')
        records['explanation']['status'] = 'technical_failure'
        self.assertEqual(aggregate(records, c)['status'], 'technical_failure')

    def test_schema_priority_validation_and_real_adapter_without_network(self):
        from openai.resources.chat.completions import Completions
        c = visible_case(fixture())
        for role in ('single', 'preference', 'attribute', 'explanation'):
            fixture_record = BenchmarkFixtureProvider().assess(role, c, 'test')
            with tempfile.TemporaryDirectory() as folder, patch('macro.ai_agents.agents.openai_api_key', return_value='offline-placeholder'), patch.object(Completions, 'create', return_value=completion(fixture_record['raw'])) as sdk:
                record = LiveProvider(CONFIG, CallRecorder(folder, 3)).assess(role, c, 'test_attempt-01')
                self.assertEqual(record['schema_version'], 'benchmark-assessment-v2')
                wire = sdk.call_args.kwargs['response_format']['json_schema']['schema']
                self.assertEqual(wire, response_schema(role, c))
        raw = self.records(fixture())['single']['assessment']
        raw['priorities'] = ['speed', 'speed']
        with self.assertRaises(AssessmentValidationError):
            validate_assessment('single', raw, c)

    def test_v2_package_portable_and_content_changes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'benchmark-v2'
            shutil.copytree(PACKAGE, out)
            manifest = read_json(out / 'manifest.json')
            self.assertEqual(manifest['splits']['test']['base_cases'], 400)
            for name in manifest['hashes']:
                path = out / name
                path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
            verify_saved(out)
            path = out / 'test/cases.jsonl'
            path.write_bytes(path.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'Artifact hash mismatch'):
                verify_saved(out)

    def test_coordinator_matches_all_v2_references_in_both_orders(self):
        # Perfect synthetic specialist findings test aggregation, not LLM accuracy.
        for split in ('dev', 'test'):
            refs = {r['case_id']: r for r in read_jsonl(PACKAGE / 'private' / (split + '.references.jsonl'))}
            for c in read_jsonl(PACKAGE / split / 'cases.jsonl'):
                expected = refs[c['case_id']]['verdict']
                for case, verdict in ((c, expected), (swapped(c), {'A': 'B', 'B': 'A'}.get(expected, expected))):
                    result = aggregate(self.records(case), case)
                    self.assertEqual(result['status'], 'ok', c['case_id'])
                    self.assertEqual(result['decision'], verdict, c['case_id'])

    def test_false_comparison_labels_and_explanation_issues_cannot_vote(self):
        c = fixture()
        records = self.records(c)
        records['attribute']['assessment']['speed_comparison'] = 'B'
        records['explanation']['assessment']['findings'][0]['supported'] = False
        records['explanation']['assessment']['findings'][0]['relevant_tradeoffs_disclosed'] = False
        result = aggregate(records, c)
        self.assertEqual(result['decision'], 'A')
        self.assertEqual(result['comparison_diagnostics'][0]['criterion'], 'speed')
        self.assertEqual(result['diagnostics'], ['A: explanation issue'])
        # Coordinator uses explicitly declared public priorities, not a misextraction.
        records['preference']['assessment']['priorities'] = ['nutrition', 'speed', 'preference']
        result = aggregate(records, c)
        self.assertEqual(result['decision'], 'A')
        self.assertFalse(result['priority_extraction_matches'])

    def test_missing_duplicate_or_invalid_specialist_cannot_become_unresolved(self):
        c = fixture()
        for role in ('preference', 'attribute', 'explanation'):
            for damage in ('missing', 'duplicate', 'invalid'):
                records = self.records(c)
                if damage == 'missing':
                    del records[role]
                elif damage == 'duplicate':
                    records[role]['assessment']['findings'][1]['candidate'] = 'A'
                else:
                    records[role]['assessment'] = None
                result = aggregate(records, c)
                self.assertEqual(result['status'], 'technical_failure')
                self.assertIsNone(result['decision'])

    def test_preflight_and_full_400_pipeline_resume_report(self):
        plan = experiment_plan(PACKAGE / 'test', 400, CONFIG)
        self.assertEqual(plan['total_initial_calls'], 3200)
        with self.assertRaisesRegex(ValueError, 'policy_version'):
            experiment_plan(PACKAGE / 'test', 400, {**CONFIG, 'policy_version': 'wrong'})
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
                os.chdir(folder)
                result = _run(PACKAGE / 'test', CONFIG, lambda recorder: BenchmarkFixtureProvider(), 'offline', limit=400, max_calls=6000, run_id='benchmark-internal')
                report = read_json(result / 'summary.json')
                for system in ('single', 'specialists'):
                    self.assertEqual(report['metrics'][system]['evaluation_coverage']['correct'], 800)
                    self.assertEqual(report['metrics'][system]['candidate_order_stability']['correct'], 400)
                    self.assertEqual(report['metrics'][system]['constraint_detection']['recall'], 1.)
                    self.assertEqual(sum(v['correct'] for v in report['metrics'][system]['accuracy_by_type'].values()), 800)
                html = (result / 'report.html').read_text(encoding='utf-8')
                self.assertIn('speed comparison', html)
                self.assertIn('raw decision and verified constraints', html)
                self.assertFalse(report['is_model_performance'])
                class NoMoreCalls:
                    def assess(self, *args, **kwargs):
                        raise AssertionError('Completed assessment repeated')
                _run(PACKAGE / 'test', CONFIG, lambda recorder: NoMoreCalls(), 'offline', limit=400, max_calls=6000, run_id='benchmark-internal')
                os.chdir(previous)
        finally:
            os.chdir(previous)

    def test_raw_detection_is_not_replaced_by_guardrail_and_missing_stays_missing(self):
        c = fixture()
        c['profile']['hard_max_duration_minutes'] = 15.
        reference = dict(case_id=c['case_id'], verdict='A', case_type='constraint', candidates={
            'A': dict(feasible=True, violations=[]), 'B': dict(feasible=False, violations=['duration'])})
        result = dict(status='ok', decision='A', raw_decision='B',
                      attributes=[dict(candidate=s, feasible=True, violations=[]) for s in ('A', 'B')])
        metrics = compute([c], [reference], {(c['case_id'], 'original', 'single'): result})['single']
        self.assertEqual(metrics['accuracy_by_type']['constraint'], dict(correct=1, total=2, rate=.5))
        self.assertEqual(metrics['constraint_detection']['fn'], 1)
        self.assertEqual(metrics['constraint_detection']['recall'], 0.)
        self.assertEqual(metrics['diagnostic_counts'], {'missing': 1})

    def test_final_budget_rejected_before_provider_initialization(self):
        factory = unittest.mock.Mock(side_effect=AssertionError('Provider initialized'))
        with self.assertRaisesRegex(ValueError, 'Final test execution is disabled'):
            _run(PACKAGE / 'test', CONFIG, factory, 'live', limit=400, max_calls=240)
        factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
