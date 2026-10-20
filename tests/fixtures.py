"""Internal synthetic fixtures; never used by the application run command."""
import json
from pathlib import Path
from macro.ai_agents.prompts import prompt
from macro.ai_agents.schemas import assessment_groups, validate_assessment
from macro.evaluation.runner import _run

def fixture():
    # Independent, hand-specified inputs. A is feasible; B exceeds 30 minutes.
    return {"case_id": "fixture", "profile": {"preferred_ingredients": ["garlic", "onion"],
        "excluded_ingredients": ["mushroom"], "hard_max_duration_minutes": 30.0, "objectives": ["preference", "nutrition"], "priorities": ["preference", "nutrition"]},
        "request": "No mushrooms, at most 30 minutes, preference first.",
        "candidate_pool": [
            {"id": "1", "title": "A", "duration_minutes": 30.0, "canonical_ingredients": ["garlic", "onion"], "ingredient_names": ["garlic", "onion"], "nutrition_metric": "hummus_normalized_fsa", "nutrition_score": .25},
            {"id": "2", "title": "B", "duration_minutes": 45.0, "canonical_ingredients": ["garlic"], "ingredient_names": ["garlic"], "nutrition_metric": "hummus_normalized_fsa", "nutrition_score": .875}],
        "recommendations": {"A": {"recipe_id": "1", "explanation": "30 minutes, garlic and onion, score 0.25"},
                            "B": {"recipe_id": "2", "explanation": "45 minutes, garlic, score 0.875"}}}


CONFIG = {"policy_version": "benchmark-policy-v1", "model": "gpt-5-nano", "reasoning_effort": "low", "max_completion_tokens": 3500,
          "timeout_seconds": 60, "max_attempts": 2, "max_tool_rounds": 2, "pricing": None}


def speed_fixture():
    return {'case_id': 'speed-example', 'profile': {
        'preferred_ingredients': ['garlic'], 'excluded_ingredients': [],
        'hard_max_duration_minutes': 30., 'objectives': ['preference', 'nutrition', 'speed'],
        'priorities': ['speed', 'preference', 'nutrition']}, 'request': 'Prefer quicker recipes.',
        'candidate_pool': [
            {'id': 'one', 'duration_minutes': 10., 'nutrition_score': .5,
             'nutrition_metric': 'hummus_normalized_fsa', 'canonical_ingredients': ['garlic']},
            {'id': 'two', 'duration_minutes': 20., 'nutrition_score': .75,
             'nutrition_metric': 'hummus_normalized_fsa', 'canonical_ingredients': ['garlic']}],
        'recommendations': {'A': {'recipe_id': 'one', 'explanation': '10 minutes, FSA 0.5'},
                            'B': {'recipe_id': 'two', 'explanation': '20 minutes, FSA 0.75'}}}


class OfflineProvider:
    """Synthetic public-evidence adapter for plumbing, not model-performance evidence."""
    def assess(self, role, evidence, tag, feedback=None):
        p = evidence['profile']
        prefs, attrs, expls = [], [], []
        for s in ('A', 'B'):
            i, r = next((i, r) for i, r in enumerate(evidence['candidate_pool']) if r['id'] == evidence['recommendations'][s]['recipe_id'])
            violations = []
            if p['hard_max_duration_minutes'] is not None and r['duration_minutes'] > p['hard_max_duration_minutes'] + 1e-9:
                violations.append('duration')
            violations.extend('excluded:' + g for g in p['excluded_ingredients'] if g in r['canonical_ingredients'])
            prefs.append(dict(candidate=s, preference_score=len(set(p['preferred_ingredients']) & set(r['canonical_ingredients'])) / len(p['preferred_ingredients']), evidence=[f'/candidate_pool/{i}/canonical_ingredients']))
            attrs.append(dict(candidate=s, feasible=not violations, violations=violations,
                              nutrition_score=r['nutrition_score'], duration_minutes=r['duration_minutes'], evidence=[f'/candidate_pool/{i}/duration_minutes']))
            expls.append(dict(candidate=s, supported=True, relevant_tradeoffs_disclosed=True, issues=[], evidence=[f'/recommendations/{s}/explanation']))
        comp = {}
        for name, values in [('preference', [x['preference_score'] for x in prefs]),
                             ('nutrition', [x['nutrition_score'] for x in attrs]),
                             ('speed', [-x['duration_minutes'] for x in attrs])]:
            comp[name] = 'equal' if abs(values[0] - values[1]) <= 1e-9 else 'A' if values[0] > values[1] else 'B'
        valid = [a['candidate'] for a in attrs if a['feasible']]
        active = [comp[k] for k in p['objectives'] if comp[k] != 'equal']
        if not valid:
            decision = 'both_violate'
        elif len(valid) == 1:
            decision = valid[0]
        elif not active:
            decision = 'tie'
        elif len(set(active)) == 1:
            decision = active[0]
        elif p['priorities'] is None:
            decision = 'insufficient_information'
        else:
            decision = next(comp[k] for k in p['priorities'] if comp[k] != 'equal')
        if role == 'single':
            result = dict(preferences=prefs, attributes=attrs, explanations=expls, priorities=p['priorities'], decision=decision,
                          **{k + '_comparison': v for k, v in comp.items()})
        elif role == 'preference':
            result = dict(findings=prefs, preference_comparison=comp['preference'], priorities=p['priorities'])
        elif role == 'attribute':
            result = dict(findings=attrs, nutrition_comparison=comp['nutrition'], speed_comparison=comp['speed'])
        else:
            result = dict(findings=expls)
        result['rationale'] = 'Internal synthetic fixture, not model evidence.'
        raw = json.dumps(as_wire(role, result))
        system, user = prompt(role, evidence)
        return dict(status='ok', assessment=validate_assessment(role, raw, evidence), raw=raw,
                    system_prompt=system, user_prompt=user, tool_calls=[], provider='offline_fixture')


def as_wire(role, result):
    result = json.loads(json.dumps(result))
    for group in assessment_groups(role):
        result[group] = {finding["candidate"]: {key: value for key, value in finding.items() if key != "candidate"}
                         for finding in result[group]}
    return result


def completion(raw):
    from openai.types.chat import ChatCompletion
    return ChatCompletion.model_validate({"id": "mock", "object": "chat.completion", "created": 0,
        "model": "gpt-5-nano", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": raw}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})



def write_fixture_package(folder):
    """Write one verified current-schema case for isolated runner tests."""
    from macro.evaluate_case_generation.benchmark import STRATA, request, factual_explanation, profile_identity
    from macro.shared.benchmark_policy import evaluate_case
    from macro.shared.io import digest, file_hash, write_json, write_jsonl
    folder = Path(folder)
    case = fixture()
    case['request'] = request(case['profile'])
    for slot, recommendation in case['recommendations'].items():
        recipe = next(r for r in case['candidate_pool'] if r['id'] == recommendation['recipe_id'])
        recommendation['explanation'] = factual_explanation(recipe)
    ref = {**evaluate_case(case), 'stratum': 'constraint_duration_clear', 'profile_id': profile_identity(case['profile'])}
    config = {'strata': {s: {'dev': 0, 'test': int(s == ref['stratum'])} for s in STRATA}}
    hashes = {}
    for split in ('dev', 'test'):
        for relative, rows in [(f'{split}/cases.jsonl', [case] if split == 'test' else []),
                               (f'private/{split}.references.jsonl', [ref] if split == 'test' else [])]:
            write_jsonl(folder / relative, rows)
            hashes[relative] = file_hash(folder / relative)
    write_json(folder / 'config.json', config)
    write_json(folder / 'manifest.json', {'version': 'test-fixture', 'policy_version': 'benchmark-policy-v1',
               'status': 'internal_fixture', 'config_sha256': digest(config), 'hashes': hashes})
    return folder / 'test'


def run_fixture(folder, config, **kwargs):
    kwargs.setdefault('max_calls', 240)
    return _run(folder, config, lambda recorder: OfflineProvider(), 'offline', **kwargs)
