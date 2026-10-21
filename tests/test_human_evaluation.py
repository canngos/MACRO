"""Sampling, blinding and orientation checks without model calls."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_human_evaluation import CATEGORIES, generate, make_sample, render_html


class HumanEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'source'
        self.run.mkdir()
        (self.run / 'evaluations').mkdir()
        (self.run / 'manifest.json').write_text('{}')
        cases, refs = [], []
        for kind in CATEGORIES:
            for i in range(12):
                cid = f'{kind}-{i:02d}'
                cases.append({'case_id': cid, 'request': 'Use supplied evidence.', 'private_label': 'DO_NOT_SHARE',
                              'profile': {'objectives': ['nutrition'], 'priorities': None,
                                          'preferred_ingredients': [], 'excluded_ingredients': [],
                                          'hard_max_duration_minutes': None},
                              'candidate_pool': [{'id': 'one', 'duration_minutes': 10, 'nutrition_score': .75,
                                                  'nutrition_metric': 'hummus_normalized_fsa', 'canonical_ingredients': ['garlic']},
                                                 {'id': 'two', 'duration_minutes': 20, 'nutrition_score': .25,
                                                  'nutrition_metric': 'hummus_normalized_fsa', 'canonical_ingredients': ['onion']}],
                              'recommendations': {'A': {'recipe_id': 'one', 'explanation': 'First explanation'},
                                                  'B': {'recipe_id': 'two', 'explanation': 'Second explanation'}}})
                refs.append({'case_id': cid, 'case_type': kind, 'verdict': 'A',
                             'candidates': {'A': {'recipe_id': 'one', 'feasible': True},
                                            'B': {'recipe_id': 'two', 'feasible': True}}})
                for order in ('original', 'reversed'):
                    for system in ('single', 'specialists'):
                        row = {'case_id': cid, 'order': order, 'system': system,
                               'status': 'technical_failure' if i == 0 else 'ok',
                               'decision': None if i == 0 else 'A' if order == 'original' else 'B',
                               'private_marker': 'MODEL_ANSWER_HIDDEN'}
                        (self.run / 'evaluations' / f'{cid}-{order}-{system}.json').write_text(json.dumps(row))
        self.cases, self.refs = cases, refs
        self.write_inputs(cases, refs)

    def write_inputs(self, cases, refs):
        for name, rows in [('cases.snapshot.jsonl', cases), ('references.snapshot.private.jsonl', refs)]:
            (self.run / name).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_50_unique_cases_balanced_by_category(self):
        packet, key, manifest = make_sample(self.run)
        self.assertEqual(len(packet['cases']), 50)
        self.assertEqual(len({r['source_case_id'] for r in key}), 50)
        self.assertEqual(manifest['sample_by_class'], dict.fromkeys(CATEGORIES, 10))
        self.assertFalse(manifest['selection_depends_on_model_outcomes'])

    def test_reproducible_independent_of_input_row_order(self):
        packet, key, _ = make_sample(self.run, seed=42)
        self.write_inputs(list(reversed(self.cases)), list(reversed(self.refs)))
        second_packet, second_key, _ = make_sample(self.run, seed=42)
        self.assertEqual(packet, second_packet)
        self.assertEqual(key, second_key)
        self.assertNotEqual(key, make_sample(self.run, seed=43)[1])

    def test_displayed_orientation_reference_and_model_outputs_match(self):
        packet, key, _ = make_sample(self.run)
        self.assertEqual({r['source_order'] for r in key}, {'original', 'reversed'})
        for public, private in zip(packet['cases'], key):
            swapped = private['source_order'] == 'reversed'
            self.assertEqual(public['candidates']['A']['duration_minutes'], 20 if swapped else 10)
            self.assertEqual(private['reference_displayed']['verdict'], 'B' if swapped else 'A')
            self.assertEqual(private['reference_displayed']['candidates']['A']['recipe_id'], 'two' if swapped else 'one')
            for model in private['model_results'].values():
                self.assertEqual(model['order'], private['source_order'])

    def test_public_packet_hides_case_ids_categories_and_model_answers(self):
        packet, key, _ = make_sample(self.run)
        serialized = json.dumps(packet)
        html = render_html(packet)
        for secret in ('DO_NOT_SHARE', 'MODEL_ANSWER_HIDDEN', 'source_case_id', 'reference_displayed', 'model_results'):
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, html)
        self.assertTrue(all(set(c) == {'sample_id', 'profile', 'request', 'candidates'} for c in packet['cases']))
        self.assertIn('MODEL_ANSWER_HIDDEN', json.dumps(key))

    def test_failures_and_missing_results_are_not_filtered_out(self):
        packet, key, _ = make_sample(self.run, per_class=12)
        self.assertEqual(len(packet['cases']), 60)
        self.assertTrue(any(r['model_results']['single']['status'] == 'technical_failure' for r in key))
        for path in (self.run / 'evaluations').glob('*.json'):
            path.unlink()
        _, missing, _ = make_sample(self.run)
        self.assertTrue(all(r['model_results']['single']['status'] == 'missing' for r in missing))

    def test_insufficient_class_fails_before_output(self):
        self.write_inputs(self.cases[:-3], self.refs[:-3])
        out = self.root / 'out'
        with self.assertRaisesRegex(ValueError, 'need 10'):
            generate(self.run, out)
        self.assertFalse(out.exists())

    def test_output_preserves_source_and_refuses_overwrite(self):
        before = {str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        out = self.root / 'out'
        generate(self.run, out)
        with (out / 'packet/responses.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 50)
        self.assertTrue(all(not r['verdict'] and not r['rater_id'] for r in rows))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            generate(self.run, out)
        with self.assertRaisesRegex(ValueError, 'outside'):
            generate(self.run, self.run / 'inside')
        self.assertEqual(before, {str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob('*') if p.is_file()})

    def test_html_escapes_untrusted_recipe_strings(self):
        packet, _, _ = make_sample(self.run)
        packet['cases'][0]['candidates']['A']['explanation'] = '</script><img src=x onerror=alert(1)>'
        html = render_html(packet)
        self.assertNotIn('</script><img', html)
        self.assertIn('&lt;/script&gt;&lt;img', html)
