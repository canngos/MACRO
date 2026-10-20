"""Read-only pre-final audit. Does not approve human review or call model APIs."""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from macro.evaluate_case_generation.benchmark import verify_saved
from macro.evaluation.runner import source_code_hashes
from macro.shared.io import file_hash, read_json, read_jsonl, write_json


def lengths(case):
    texts = [case['recommendations'][s]['explanation'] for s in ('A', 'B')]
    chars = [len(t) for t in texts]
    words = [len(t.split()) for t in texts]
    return chars + words + [abs(chars[0] - chars[1]), sum(chars)]


def stump(train_x, train_y, test_x):
    """Fit a single length threshold on development only; deterministic ties."""
    def majority(labels):
        counts = Counter(labels)
        return sorted(counts, key=lambda label: (-counts[label], label))[0]
    fallback = majority(train_y)
    best = (-1, 0, float('inf'), fallback, fallback)
    for index in range(len(train_x[0])):
        values = sorted({row[index] for row in train_x})
        for threshold in values:
            left = [y for x, y in zip(train_x, train_y) if x[index] <= threshold]
            right = [y for x, y in zip(train_x, train_y) if x[index] > threshold]
            a, b = majority(left) if left else fallback, majority(right) if right else fallback
            score = sum(y == (a if x[index] <= threshold else b) for x, y in zip(train_x, train_y))
            if score > best[0]:
                best = (score, index, threshold, a, b)
    _, index, threshold, a, b = best
    return [a if x[index] <= threshold else b for x in test_x], {
        'feature': ['characters_A', 'characters_B', 'words_A', 'words_B', 'character_difference', 'character_total'][index],
        'threshold': threshold, 'lower_label': a, 'upper_label': b}


def surface_checks(cases, refs):
    train_x, test_x = [lengths(c) for c in cases['dev']], [lengths(c) for c in cases['test']]
    result = {}
    for target in ('verdict', 'case_type'):
        train_y = [refs['dev'][c['case_id']][target] for c in cases['dev']]
        test_y = [refs['test'][c['case_id']][target] for c in cases['test']]
        predictions, model = stump(train_x, train_y, test_x)
        score = sum(a == b for a, b in zip(predictions, test_y)) / len(test_y)
        result[target] = {'method': 'Development-fitted decision stump on six explanation-length features only',
                          'test_accuracy': score,
                          'test_majority_baseline': max(Counter(test_y).values()) / len(test_y),
                          'model': model}
    def skeleton(case):
        texts = []
        for slot in ('A', 'B'):
            text = case['recommendations'][slot]['explanation']
            text = re.sub(r'Duration: [0-9.]+ minutes\.', 'Duration: <duration> minutes.', text)
            text = re.sub(r'Documented ingredient groups: .*?\. Normalized',
                          'Documented ingredient groups: <groups>. Normalized', text)
            text = re.sub(r'proxy: [0-9.]+;', 'proxy: <score>;', text)
            texts.append(text)
        return tuple(texts)
    train_surface = [skeleton(c) for c in cases['dev']]
    test_surface = [skeleton(c) for c in cases['test']]
    result['fact_masked_surface'] = {'dev_unique_templates': len(set(train_surface)),
                                    'test_unique_templates': len(set(test_surface)),
                                    'templates_match_between_splits': set(train_surface) == set(test_surface),
                                    'interpretation': 'After masking duration, ingredient list and nutrition value, all base explanations have identical style.'}
    for target in ('verdict', 'case_type'):
        labels = [refs['dev'][c['case_id']][target] for c in cases['dev']]
        majority = sorted(Counter(labels), key=lambda k: (-labels.count(k), k))[0]
        result['fact_masked_surface'][target + '_majority_classifier_accuracy'] = sum(
            refs['test'][c['case_id']][target] == majority for c in cases['test']) / len(cases['test'])
    groups = defaultdict(list)
    for case in cases['dev']:
        groups[refs['dev'][case['case_id']]['case_type']].append(lengths(case)[-1])
    result['dev_total_characters_by_category'] = {
        k: {'min': min(v), 'max': max(v), 'mean': sum(v) / len(v)} for k, v in groups.items()}
    result['interpretation'] = ('Diagnostic only, not an automatic pass or a comprehensive leakage test. '
        'Lengths can encode intended factual content such as ingredient counts. '
        'No test model outputs were used and no judge settings were tuned. '
        'The study owner must review these diagnostics and accept or resolve any shortcut concerns before freeze.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='data/benchmark-v2')
    parser.add_argument('--development-run', required=True)
    parser.add_argument('--source', default='../pp_recipes/pp_recipes.csv')
    parser.add_argument('--out', default='readiness/deepseek-final-400')
    args = parser.parse_args()
    dataset, dev, out = Path(args.dataset), Path(args.development_run), Path(args.out)
    manifest, run = read_json(dataset / 'manifest.json'), read_json(dev / 'manifest.json')
    summary = read_json(dev / 'summary.json')
    integrity = verify_saved(dataset)
    cases = {s: read_jsonl(dataset / s / 'cases.jsonl') for s in ('dev', 'test')}
    refs = {s: {r['case_id']: r for r in read_jsonl(dataset / 'private' / (s + '.references.jsonl'))}
            for s in ('dev', 'test')}
    source_map = read_json(dataset / 'private/source_map.json')
    subset = {r['id']: r for r in read_jsonl('data/subset-v1/recipes.jsonl')}
    source_ids = {m['source_recipe_id'] for m in source_map.values()}
    source_errors, checked = [], set()
    for split in cases:
        for case in cases[split]:
            for recipe in case['candidate_pool']:
                mapped = source_map[recipe['id']]
                original = subset[mapped['source_recipe_id']]
                for key, value in recipe.items():
                    if key != 'id' and value != original.get(key):
                        source_errors.append({'recipe': recipe['id'], 'field': key, 'stage': 'benchmark_to_subset'})
                if original['source_record_number'] != mapped['source_record_number']:
                    source_errors.append({'recipe': recipe['id'], 'field': 'source_record_number'})
    with Path(args.source).open(encoding='utf-8', newline='') as stream:
        for number, row in enumerate(csv.DictReader(stream), 1):
            rid = row['recipe_id']
            if rid not in source_ids:
                continue
            original = subset[rid]
            if original['source_record_number'] != number or any(row[k] != v for k, v in original['source_values'].items()):
                source_errors.append({'source_recipe_id': rid, 'stage': 'subset_to_csv'})
            checked.add(rid)
    if checked != source_ids:
        source_errors.append({'stage': 'missing_source_records', 'count': len(source_ids - checked)})
    source_hash = file_hash(args.source)
    if source_hash != manifest['subset_source_sha256']:
        source_errors.append({'stage': 'source_file_hash'})
    current_hashes = source_code_hashes()
    code_changes = [k for k in set(current_hashes) | set(run['code_hashes'])
                    if current_hashes.get(k) != run['code_hashes'].get(k)]
    failures = []
    for path in (dev / 'evaluations').glob('*.json'):
        result = read_json(path)
        if result['status'] != 'ok':
            failures.append({'file': path.name, 'status': result['status']})
    report = {
        'purpose': 'Readiness evidence, not a human approval or final freeze',
        'development_run': str(dev), 'development_manifest_sha256': file_hash(dev / 'manifest.json'),
        'dataset_manifest_sha256': file_hash(dataset / 'manifest.json'),
        'scope': '400 factual-base cases, both candidate orders; no explanation variants',
        'integrity': integrity,
        'source_correspondence': {'recipes_checked': len(checked), 'errors': source_errors,
                                  'source_sha256': source_hash, 'human_semantic_review': 'pending'},
        'development': {'code_changes_since_run': code_changes,
                        'configuration_matches': run['config'] == read_json('configs/deepseek-pilot.json'),
                        'evaluations': {s: summary['metrics'][s]['evaluation_coverage'] for s in ('single', 'specialists')},
                        'primary_accuracy': {s: summary['metrics'][s]['overall_accuracy'] for s in ('single', 'specialists')},
                        'raw_accuracy': {s: summary['raw_metrics'][s]['overall_accuracy'] for s in ('single', 'specialists')},
                        'technical_failures': failures},
        'surface_diagnostics': surface_checks(cases, refs),
        'readiness': 'pending human/source review, leakage-diagnostic review, and freeze; no model calls made',
    }
    write_json(out / 'checks.json', report)
    lines = ['# Final 400-case readiness review', '',
             'This review prepares the final run. It does not mark human review complete or enable paid inference.', '',
             f'Development run: `{dev.name}`. Scope: 400 factual base cases, each in both orders.', '',
             '| System | Completed / planned | Primary correct / planned | Raw correct / planned |',
             '|---|---:|---:|---:|']
    for system in ('single', 'specialists'):
        m = summary['metrics'][system]
        raw = summary['raw_metrics'][system]['overall_accuracy']
        lines.append(f"| {system} | {m['evaluation_coverage']['correct']}/240 | {m['overall_accuracy']['correct']}/240 | {raw['correct']}/240 |")
    lines += ['', f'Source correspondence: {len(checked)} recipes checked against the local CSV; {len(source_errors)} mismatches.',
              'This confirms transcription/provenance, not independent verification that recipe facts or ingredient mappings are true.', '',
              f'Code changes since development: {json.dumps(code_changes)}.',
              f'Final technical failures in development: {json.dumps(failures)}.', '',
              '## Length-only surface diagnostics', '',
              '| Target | Development-fitted stump accuracy on test metadata | Test majority baseline |',
              '|---|---:|---:|']
    for target in ('verdict', 'case_type'):
        r = report['surface_diagnostics'][target]
        lines.append(f"| {target} | {r['test_accuracy']:.3f} | {r['test_majority_baseline']:.3f} |")
    lines += ['', report['surface_diagnostics']['interpretation'], '',
              '## Outstanding decisions', '',
              '- Provide the manual/source review record; no such benchmark review record was found locally.',
              '- Review surface diagnostics and document their implications; these do not automatically pass a leakage check.',
              '- Accept the recorded development failures and freeze the selected configuration, dataset, scope and source code.',
              '- Enable final execution only through a verified readiness record. The current runner rejects final inference.', '',
              'No prompt, model setting, dataset label, source artifact, or existing result was changed by this audit.']
    (out / 'REVIEW.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(out), 'source_records_checked': len(checked), 'source_mismatches': len(source_errors),
                      'surface_diagnostics': report['surface_diagnostics'], 'readiness': report['readiness']}, indent=2))


if __name__ == '__main__':
    main()
