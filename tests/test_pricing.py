"""Hand-calculated cost checks; no live API calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.reporting.pricing import cache_usage, estimate, validate_pricing
from macro.reporting.summary import summarize
from macro.shared.io import read_json, write_json, write_jsonl
from macro.shared.benchmark_policy import evaluate_case
from tests.fixtures import fixture, OfflineProvider, completion

ROOT = Path(__file__).resolve().parents[1]
CONFIG = read_json(ROOT / 'configs/deepseek-pilot.json')
PRICING = CONFIG['pricing']


def call(hit=400_000, miss=600_000, output=100_000, **extra):
    return {'role': 'single', 'tag': 'example_attempt-01', 'status': 'complete',
            'usage': {'prompt_tokens': hit + miss, 'completion_tokens': output,
                      'total_tokens': hit + miss + output,
                      'prompt_cache_hit_tokens': hit, 'prompt_cache_miss_tokens': miss}, **extra}


class PricingTests(unittest.TestCase):
    def test_both_configs_have_the_official_flash_rates(self):
        other = read_json(ROOT / 'configs/deepseek-thinking-pilot.json')['pricing']
        self.assertEqual(PRICING, other)
        self.assertEqual((PRICING['input_per_million'], PRICING['cached_input_per_million'], PRICING['output_per_million']), (.3, .006, 1.2))
        self.assertEqual(PRICING['off_peak'], {'input_per_million': .15, 'cached_input_per_million': .003, 'output_per_million': .6})
        validate_pricing(PRICING)

    def test_cache_aware_peak_and_off_peak_hand_calculation(self):
        result = estimate([call()], PRICING)
        # 0.4M hits * .006 + 0.6M misses * .3 + 0.1M output * 1.2.
        self.assertAlmostEqual(result['currency_estimate'], .3024)
        self.assertAlmostEqual(result['currency_estimate_lower'], .1512)
        self.assertAlmostEqual(result['off_peak_currency_estimate'], .1512)
        self.assertEqual(result['currency_estimate_upper'], result['currency_estimate'])

    def test_sdk_cache_details_and_missing_half_of_breakdown(self):
        row = call()
        row['usage'].pop('prompt_cache_hit_tokens')
        row['usage'].pop('prompt_cache_miss_tokens')
        row['usage']['prompt_tokens_details'] = {'cached_tokens': 400_000}
        self.assertAlmostEqual(estimate([row], PRICING)['currency_estimate'], .3024)
        row['usage'].pop('prompt_tokens_details')
        row['usage']['prompt_cache_miss_tokens'] = 600_000
        self.assertEqual(cache_usage([row])['cache_hit_tokens'], 400_000)

    def test_missing_or_inconsistent_cache_metadata_does_not_mean_zero_cost(self):
        row = call()
        row['usage'].pop('prompt_cache_hit_tokens')
        row['usage'].pop('prompt_cache_miss_tokens')
        result = estimate([row], PRICING)
        self.assertEqual(result['input_tokens_without_cache_breakdown'], 1_000_000)
        self.assertAlmostEqual(result['currency_estimate'], .42)
        self.assertAlmostEqual(result['currency_estimate_lower'], .063)
        row['usage'].update(prompt_cache_hit_tokens=1_000_001, prompt_cache_miss_tokens=0)
        self.assertEqual(cache_usage([row])['input_tokens_without_cache_breakdown'], 1_000_000)

    def test_unknown_usage_omitted_retries_and_followups_included(self):
        retry = call(tag='example_attempt-02')
        result = estimate([call(), retry, {'usage': None}], PRICING)
        self.assertAlmostEqual(result['currency_estimate'], .6048)
        self.assertIn('cost is unknown', result['note'])
        self.assertIsNone(estimate([], None)['currency_estimate'])

    def test_legacy_flat_pricing_retains_uncached_estimate(self):
        legacy = {k: v for k, v in PRICING.items() if k not in ('cached_input_per_million', 'off_peak')}
        self.assertAlmostEqual(estimate([call()], legacy)['currency_estimate'], .42)

    def test_invalid_rates_rejected(self):
        for value in (-1, float('nan'), True, '0.3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                estimate([call()], {**PRICING, 'input_per_million': value})
        with self.assertRaises(ValueError):
            estimate([call()], {**PRICING, 'cached_input_per_million': .4})

    def test_ag2_gets_per_thousand_peak_price_but_sdk_does_not(self):
        from openai.resources.chat.completions import Completions
        from macro.ai_agents.agents import LiveProvider, llm_settings
        from macro.ai_agents.prompts import visible_case
        from macro.evaluation.runner import CallRecorder
        settings = llm_settings(CONFIG, 'placeholder', {})
        self.assertEqual(settings['price'], [.0003, .0012])
        evidence = visible_case(fixture())
        raw = OfflineProvider().assess('single', evidence, 'test')['raw']
        with tempfile.TemporaryDirectory() as folder, \
                patch('macro.ai_agents.agents.api_key', return_value='offline-key'), \
                patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), \
                patch.object(Completions, 'create', return_value=completion(raw)) as sdk:
            LiveProvider(CONFIG, CallRecorder(folder, 3)).assess('single', evidence, 'test_attempt-01')
        self.assertNotIn('price', sdk.call_args.kwargs)
        self.assertEqual(sdk.call_args.kwargs['response_format'], {'type': 'json_object'})

    def test_report_totals_and_system_costs_agree(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            case = fixture()
            write_json(folder / 'manifest.json', {'mode': 'live', 'config': CONFIG,
                       'policy_version': 'benchmark-policy-v1', 'split': 'dev',
                       'prompt_version': 'benchmark-judges-v2', 'schema_version': 'benchmark-assessment-v2'})
            write_jsonl(folder / 'cases.snapshot.jsonl', [case])
            write_jsonl(folder / 'references.snapshot.private.jsonl', [evaluate_case(case)])
            (folder / 'evaluations').mkdir()
            write_json(folder / 'calls/one.json', call())
            write_json(folder / 'calls/two.json', call(role='attribute', tag='example_attempt-02'))
            write_json(folder / 'calls/three.json', {'role': 'explanation', 'tag': 'example_attempt-01', 'status': 'error', 'usage': None})
            report = summarize(folder)
            self.assertAlmostEqual(report['costs']['currency_estimate'], .6048)
            self.assertAlmostEqual(sum(x['currency_estimate'] for x in report['costs_by_system'].values()), .6048)
            self.assertEqual(report['costs']['calls_without_usage'], 1)
            self.assertEqual(report['costs']['retry_attempt_calls'], 1)
            self.assertIn('Known-usage cost range', (folder / 'report.html').read_text(encoding='utf-8'))
            self.assertIn('0.302400', (folder / 'report.md').read_text(encoding='utf-8'))
