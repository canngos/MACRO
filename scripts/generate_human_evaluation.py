"""Create a reproducible, blinded, category-balanced human evaluation packet.

No model calls or writes to the source run. One candidate order per unique base case.
"""
import argparse
import copy
import csv
import hashlib
from html import escape
import json
from pathlib import Path
import random

CATEGORIES = ('constraint', 'dominance', 'tradeoff', 'control_tie', 'both_violate')
FIELDS = ('sample_id', 'rater_id', 'feasible_A', 'feasible_B', 'verdict', 'confidence',
          'supported_A', 'supported_B', 'disclosed_A', 'disclosed_B', 'evidence_issue', 'notes')
RUBRIC = '''Use only the supplied facts and the documented canonical ingredient groups.
First check hard constraints: duration must be no greater than the stated maximum
(a null limit means no limit), and no excluded canonical group may be present.
If both candidates fail, select both_violate. If only one is feasible, select it.
Among feasible candidates, use only active objectives. Preference is the fraction
of distinct preferred groups present. Higher supplied nutrition_score is better;
it is a dataset proxy, not a health judgment. Speed means shorter duration, only
when speed is active. A hard duration limit does not automatically activate speed.
Equal scores on all active objectives mean tie, even if priorities are null.
If one candidate is at least as good on all active objectives and better on one,
select it. Otherwise follow the highest-first priorities, skipping equal objectives.
If active objectives conflict and priorities are null, select insufficient_information.
Do not invent weights, aliases, hidden ingredients, dietary rules or personal preferences.
Whole olives and olive oil are distinct under this bounded mapping: oil is not an olive group.
Explanation support means its factual claims match the supplied evidence. A truthful
description of an infeasible recipe is not false. For optional disclosure judgments,
mark yes if all relevant factual differences/violations are explicitly acknowledged,
no if a relevant disadvantage is omitted, and uncertain if you cannot judge. If no
relevant disadvantage exists, mark yes. These diagnostics do not change the verdict.
Use unable_to_assess for a case you cannot evaluate; this is separate from a genuine
trade-off without priorities. Flag suspected evidence problems and explain them in notes.'''


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def human_case(case, sample_id, order):
    pool = {r['id']: r for r in case['candidate_pool']}
    slots = {'A': 'B', 'B': 'A'} if order == 'reversed' else {'A': 'A', 'B': 'B'}
    candidates = {}
    for displayed, original in slots.items():
        recommendation = case['recommendations'][original]
        recipe = pool[recommendation['recipe_id']]
        candidates[displayed] = {key: copy.deepcopy(recipe[key]) for key in (
            'duration_minutes', 'nutrition_score', 'nutrition_metric', 'canonical_ingredients',
            'ingredient_names', 'raw_ingredient_names') if key in recipe}
        candidates[displayed]['explanation'] = recommendation['explanation']
    return {'sample_id': sample_id, 'profile': copy.deepcopy(case['profile']),
            'request': case['request'], 'candidates': candidates}


def make_sample(run_dir, per_class=10, seed=42):
    if type(per_class) is not int or per_class <= 0:
        raise ValueError('per_class must be a positive integer')
    run_dir = Path(run_dir)
    cases = read_jsonl(run_dir / 'cases.snapshot.jsonl')
    refs = read_jsonl(run_dir / 'references.snapshot.private.jsonl')
    lookup, references = {c['case_id']: c for c in cases}, {r['case_id']: r for r in refs}
    if len(lookup) != len(cases) or len(references) != len(refs) or set(lookup) != set(references):
        raise ValueError('Source case/reference IDs must be unique and match exactly')
    by_class = {kind: [] for kind in CATEGORIES}
    for cid in sorted(lookup):
        kind = references[cid]['case_type']
        if kind not in by_class:
            raise ValueError('Unsupported benchmark category: ' + kind)
        by_class[kind].append(cid)
    for kind, ids in by_class.items():
        if len(ids) < per_class:
            raise ValueError(f'{kind} has {len(ids)} cases; need {per_class}')
    results, result_paths = {}, {}
    for path in sorted((run_dir / 'evaluations').glob('*.json')):
        row = read_json(path)
        key = (row['case_id'], row['order'], row['system'])
        if key in results:
            raise ValueError('Duplicate saved evaluation for ' + str(key))
        results[key], result_paths[key] = row, path
    rng = random.Random(seed)
    selected = [cid for kind in CATEGORIES for cid in rng.sample(by_class[kind], per_class)]
    rng.shuffle(selected)
    public, private, selected_hashes = [], [], {}
    for index, cid in enumerate(selected, 1):
        sample_id = f'H{index:03d}'
        order = rng.choice(('original', 'reversed'))
        original_for_display = {'A': 'B', 'B': 'A'} if order == 'reversed' else {'A': 'A', 'B': 'B'}
        public.append(human_case(lookup[cid], sample_id, order))
        ref = references[cid]
        verdict = ref['verdict']
        if order == 'reversed':
            verdict = {'A': 'B', 'B': 'A'}.get(verdict, verdict)
        model_results = {}
        for system in ('single', 'specialists'):
            key = (cid, order, system)
            # Sampling never depends on correctness, agreement or completion.
            model_results[system] = copy.deepcopy(results.get(key, {'status': 'missing', 'decision': None}))
            if key in result_paths:
                selected_hashes[result_paths[key].name] = sha(result_paths[key])
        private.append({'sample_id': sample_id, 'source_case_id': cid, 'category': ref['case_type'],
                        'source_order': order, 'reference_original': copy.deepcopy(ref),
                        'reference_displayed': {'verdict': verdict, 'candidates': {
                            displayed: copy.deepcopy(ref['candidates'][original])
                            for displayed, original in original_for_display.items()}},
                        'model_results': model_results})
    manifest = {'format_version': 'human-evaluation-v1', 'seed': seed, 'per_class': per_class,
                'total_samples': len(public), 'balance_unit': 'benchmark category, not verdict label',
                'sampling_unit': 'unique base case, one randomly chosen displayed order',
                'population_by_class': {k: len(v) for k, v in by_class.items()},
                'sample_by_class': {k: per_class for k in CATEGORIES},
                'selection_depends_on_model_outcomes': False,
                'run_dir': str(run_dir.resolve()),
                'source_hashes': {name: sha(run_dir / name) for name in (
                    'manifest.json', 'cases.snapshot.jsonl', 'references.snapshot.private.jsonl')},
                'selected_evaluation_hashes': selected_hashes}
    return {'format_version': 'human-evaluation-v1', 'rubric': RUBRIC, 'cases': public}, private, manifest


def render_html(packet):
    esc = lambda value: escape(str(value), quote=True)
    articles = []
    for case in packet['cases']:
        sid = case['sample_id']
        profile = case['profile']
        profile_rows = ''.join(f'<tr><th>{esc(k.replace("_", " "))}</th><td>{esc(json.dumps(v, ensure_ascii=False))}</td></tr>'
                               for k, v in profile.items())
        candidates = []
        for slot, recipe in case['candidates'].items():
            candidates.append(f'<section class="candidate"><h3>Candidate {slot}</h3>'
                f'<p><strong>Duration:</strong> {esc(recipe["duration_minutes"])} minutes<br>'
                f'<strong>Nutrition proxy:</strong> {esc(recipe["nutrition_score"])}<br>'
                f'<strong>Canonical groups:</strong> {esc(", ".join(recipe["canonical_ingredients"]) or "none")}</p>'
                f'<p><strong>Explanation:</strong> {esc(recipe["explanation"])}</p>'
                f'<details><summary>Source ingredient strings</summary><p>{esc("; ".join(recipe.get("raw_ingredient_names", recipe.get("ingredient_names", []))))}</p></details></section>')
        def select(field, label, choices):
            options = '<option value="">Choose…</option>' + ''.join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in choices)
            return f'<label>{esc(label)}<select data-field="{field}">{options}</select></label>'
        inputs = select('feasible_A', 'A satisfies all hard constraints', ['yes', 'no', 'uncertain'])
        inputs += select('feasible_B', 'B satisfies all hard constraints', ['yes', 'no', 'uncertain'])
        inputs += select('verdict', 'Your verdict', ['A', 'B', 'tie', 'insufficient_information', 'both_violate', 'unable_to_assess'])
        inputs += select('confidence', 'Confidence', ['low', 'medium', 'high'])
        inputs += select('evidence_issue', 'Suspected problem with supplied evidence', ['no', 'yes', 'uncertain'])
        for field, label in [('supported_A', 'A explanation factually supported (optional)'),
                             ('supported_B', 'B explanation factually supported (optional)'),
                             ('disclosed_A', 'A relevant disadvantages disclosed (optional)'),
                             ('disclosed_B', 'B relevant disadvantages disclosed (optional)')]:
            inputs += select(field, label, ['yes', 'no', 'uncertain'])
        articles.append(f'<article data-sample="{sid}"><h2>{sid}</h2><p>{esc(case["request"])}</p>'
                        f'<table>{profile_rows}</table><div class="candidates">{"".join(candidates)}</div>'
                        f'<div class="answers">{inputs}</div><label>Reason for your verdict / evidence concerns'
                        '<textarea data-field="notes" rows="3"></textarea></label></article>')
    packet_id = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()[:16]
    js = r'''
const fields = FIELDS;
const storeKey = 'macro-human-' + PACKET_ID;
const rater = document.getElementById('rater');
function collect() {
  return [...document.querySelectorAll('article')].map(article => {
    const row = Object.fromEntries(fields.map(f => [f, '']));
    row.sample_id = article.dataset.sample; row.rater_id = rater.value;
    article.querySelectorAll('[data-field]').forEach(x => row[x.dataset.field] = x.value);
    return row;
  });
}
function status() {
  document.getElementById('progress').textContent = collect().filter(r => r.verdict).length + ' / ' + document.querySelectorAll('article').length + ' verdicts entered';
}
function save() {
  try { localStorage.setItem(storeKey, JSON.stringify(collect())); }
  catch (_) { document.getElementById('storage').textContent = 'Browser saving is unavailable. Export your answers frequently.'; }
  status();
}
try {
  const rows = JSON.parse(localStorage.getItem(storeKey) || '[]');
  if (rows.length) rater.value = rows[0].rater_id || '';
  rows.forEach(row => {
    const article = document.querySelector('article[data-sample="' + row.sample_id + '"]');
    if (article) article.querySelectorAll('[data-field]').forEach(x => x.value = row[x.dataset.field] || '');
  });
} catch (_) { document.getElementById('storage').textContent = 'Saved browser answers could not be loaded. Use your exported files.'; }
function download(csv) {
  const rows = collect();
  let content = JSON.stringify({packet_id: PACKET_ID, responses: rows}, null, 2);
  if (csv) {
    const quote = x => '"' + String(x ?? '').replaceAll('"', '""') + '"';
    content = '\uFEFF' + [fields, ...rows.map(row => fields.map(f => row[f]))].map(row => row.map(quote).join(',')).join('\r\n');
  }
  const blob = new Blob([content], {type: csv ? 'text/csv;charset=utf-8' : 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'human-responses-' + PACKET_ID + (csv ? '.csv' : '.json');
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.addEventListener('input', save); document.addEventListener('change', save);
document.getElementById('csv').onclick = () => download(true);
document.getElementById('json').onclick = () => download(false);
status();
'''.replace('FIELDS', json.dumps(FIELDS)).replace('PACKET_ID', json.dumps(packet_id))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Recipe comparison study</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px;background:#f5f7fa;color:#162536}'
            'article{background:white;border:1px solid #ccd5df;border-radius:10px;padding:24px;margin:24px 0}table{border-collapse:collapse;width:100%}'
            'td,th{text-align:left;border-bottom:1px solid #dde3ea;padding:7px}.candidates,.answers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}'
            '.candidate{background:#f0f5fa;padding:14px;border-radius:6px}label{display:block;margin:10px 0}select,textarea,input{display:block;width:100%;box-sizing:border-box;padding:8px;font:inherit}'
            'button{padding:10px 18px;margin:6px;font:inherit}pre{white-space:pre-wrap;font:inherit}.toolbar{position:sticky;top:0;background:#edf3fa;padding:12px;border:1px solid #ccd5df}'
            '@media(max-width:700px){.candidates,.answers{grid-template-columns:1fr}}@media print{.toolbar{position:static}article{break-before:page}button{display:none}}</style></head><body>'
            f'<h1>Recipe comparison study</h1><p>Evaluate {len(packet["cases"])} independent recipe pairs using the rules below. Model answers and reference labels are hidden.</p>'
            '<details open><summary><strong>Evaluation rules</strong></summary><pre>' + esc(RUBRIC) + '</pre></details>'
            '<p>Enter your own judgments before discussing cases with another evaluator. Use an anonymous rater code. Export files before closing; browser storage is only a convenience.</p>'
            '<div class="toolbar"><label>Your rater code<input id="rater" placeholder="e.g. R01"></label><span id="progress"></span>'
            '<button id="csv">Download responses CSV</button><button id="json">Download responses JSON</button><p id="storage"></p></div>'
            + ''.join(articles) + '<script>' + js + '</script></body></html>')


def generate(run_dir, out, per_class=10, seed=42):
    run_dir, out = Path(run_dir).resolve(), Path(out).resolve()
    if out == run_dir or run_dir in out.parents:
        raise ValueError('Output must be outside the source run directory')
    if out.exists():
        raise ValueError('Output already exists; preserve annotations and choose a new output directory')
    packet, key, manifest = make_sample(run_dir, per_class, seed)
    (out / 'packet').mkdir(parents=True)
    (out / 'private').mkdir()
    write_json(out / 'packet/cases.json', packet)
    (out / 'packet/evaluate.html').write_text(render_html(packet), encoding='utf-8', newline='\n')
    with (out / 'packet/responses.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({'sample_id': c['sample_id']} for c in packet['cases'])
    write_json(out / 'private/answer_key.json', key)
    manifest['packet_sha256'] = sha(out / 'packet/cases.json')
    manifest['generator_sha256'] = sha(__file__)
    write_json(out / 'private/manifest.json', manifest)
    (out / 'packet/README.md').write_text(
        '# Human evaluation instructions\n\nOpen `evaluate.html` in a browser. Enter an anonymous rater code, judge each case independently, and download your CSV or JSON answers. '
        'The blank `responses.csv` is an alternative for manual entry. Keep notes for ambiguous cases. '
        'Do not inspect researcher answer keys or discuss answers before submitting your independent judgments.\n\n' + RUBRIC + '\n', encoding='utf-8')
    (out / 'README.md').write_text(
        '# Researcher instructions\n\nShare **only the `packet/` folder** with evaluators. Keep `private/` hidden until judgments are submitted. '
        f'This packet contains {len(packet["cases"])} unique base cases, {per_class} from each of five benchmark categories. '
        'One randomly selected candidate order is shown per case. Sampling is independent of model correctness, agreement and failures. '
        'The private key contains original/displayed references and both systems\' saved results for that same order. '
        'Categories are balanced; A/B/tie/verdict labels need not be balanced.\n\n'
        'For multiple evaluators, give each the same unmodified packet and a separate browser profile or computer. '
        'Browser storage is shared on the same browser/profile; export and use separate profiles to avoid exposing another evaluator\'s answers. '
        'Collect independent responses before discussion. Report missing/unable-to-assess judgments explicitly. '
        'This is an annotation sample, not evidence that human review has already happened. '
        'Use returned sample_id values to join private keys after evaluation; do not treat the 50 cases as 100 independent order variants.\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, help='Completed run folder containing snapshots and evaluations')
    parser.add_argument('--out', required=True, help='New output directory outside the source run')
    parser.add_argument('--per-class', type=int, default=10, help='Default 10 gives 50 cases across five categories')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    try:
        manifest = generate(args.run_dir, args.out, args.per_class, args.seed)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(json.dumps({'samples': manifest['total_samples'], 'sample_by_class': manifest['sample_by_class'],
                      'seed': args.seed, 'human_packet': str(Path(args.out) / 'packet/evaluate.html'),
                      'private_key': str(Path(args.out) / 'private/answer_key.json')}, indent=2))


if __name__ == '__main__':
    main()
