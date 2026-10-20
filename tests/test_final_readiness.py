"""Final gates require matching, reviewed artifacts; never send paid requests."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.evaluation.readiness import verify_final_readiness
from macro.evaluation.runner import run
from macro.shared.io import digest, file_hash, write_json
from tests.fixtures import CONFIG as BASE_CONFIG

CONFIG = {**BASE_CONFIG, 'provider': 'openai'}


class FinalReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.dataset = self.folder / 'dataset'
        write_json(self.dataset / 'manifest.json', {'policy_version': 'benchmark-policy-v1'})
        self.hashes = {'ai_agents/prompts.py': 'tested-judges', 'evaluation/runner.py': 'new-final-gate'}
        self.dev = self.folder / 'development.json'
        write_json(self.dev, {'mode': 'live', 'split': 'dev', 'config': CONFIG,
                             'code_hashes': {'ai_agents/prompts.py': 'tested-judges', 'evaluation/runner.py': 'old-gate'}})
        self.evidence = self.folder / 'review.md'
        self.evidence.write_text('Synthetic test-only review evidence, not a real approval.')
        checks = self.folder / 'checks.json'
        write_json(checks, {'dataset_manifest_sha256': file_hash(self.dataset / 'manifest.json'),
                           'development_manifest_sha256': file_hash(self.dev),
                           'source_correspondence': {'recipes_checked': 1040, 'errors': []}})
        review = {'status': 'complete', 'reviewer': 'Synthetic fixture reviewer',
                  'evidence_path': str(self.evidence), 'evidence_sha256': file_hash(self.evidence)}
        self.record = {'status': 'approved', 'scope': '400_factual_base_cases_both_orders',
                       'dataset_manifest_sha256': file_hash(self.dataset / 'manifest.json'),
                       'config_digest': digest(CONFIG), 'source_code_hashes': self.hashes,
                       'development_run': {'manifest_path': str(self.dev), 'manifest_sha256': file_hash(self.dev)},
                       'automated_checks_path': str(checks), 'automated_checks_sha256': file_hash(checks),
                       **{k: copy.deepcopy(review) for k in ('source_review', 'leakage_review', 'development_review')}}
        self.path = self.folder / 'freeze.json'
        write_json(self.path, self.record)

    def verify(self, config=None, hashes=None):
        return verify_final_readiness(self.dataset, config or CONFIG, self.path, hashes or self.hashes)

    def test_approved_matching_record_accepted(self):
        self.assertEqual(self.verify()['sha256'], file_hash(self.path))

    def test_missing_pending_or_wrong_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, 'disabled'):
            verify_final_readiness(self.dataset, CONFIG, None, self.hashes)
        for key, value in [('status', 'pending_review'), ('scope', 'unreviewed_variants')]:
            record = {**self.record, key: value}
            write_json(self.path, record)
            with self.assertRaisesRegex(ValueError, 'disabled'):
                self.verify()

    def test_changed_config_dataset_or_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            self.verify(config={**CONFIG, 'max_attempts': 3})
        with self.assertRaisesRegex(ValueError, 'source code changed'):
            self.verify(hashes={**self.hashes, 'evaluation/runner.py': 'changed'})
        write_json(self.dataset / 'manifest.json', {'changed': True})
        with self.assertRaisesRegex(ValueError, 'dataset identity changed'):
            self.verify()

    def test_missing_or_changed_review_evidence_rejected(self):
        self.evidence.write_text('Altered after freeze')
        with self.assertRaisesRegex(ValueError, 'evidence is missing or changed'):
            self.verify()

    def test_pending_review_cannot_become_approved_by_top_level_status(self):
        self.record['source_review']['status'] = 'pending'
        write_json(self.path, self.record)
        with self.assertRaisesRegex(ValueError, 'source_review is pending'):
            self.verify()

    def test_untested_judge_change_rejected_even_if_frozen(self):
        changed = {**self.hashes, 'ai_agents/prompts.py': 'untested'}
        self.record['source_code_hashes'] = changed
        write_json(self.path, self.record)
        with self.assertRaisesRegex(ValueError, 'Judge or policy code changed'):
            self.verify(hashes=changed)

    def test_approved_public_run_reaches_runner_without_live_requests(self):
        with patch('macro.evaluation.runner.source_code_hashes', return_value=self.hashes), \
                patch('macro.evaluation.runner.openai_api_key', return_value='mock-key'), \
                patch('macro.evaluation.runner._run', return_value='test-only') as execute:
            result = run(self.dataset, {**CONFIG, 'provider': 'openai'}, limit=400,
                         split='test', max_calls=19200, final_readiness=self.path)
        self.assertEqual(result, 'test-only')
        execute.assert_called_once()
