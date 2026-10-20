"""Verify an explicitly reviewed experiment freeze before final-test inference."""
from pathlib import Path

from macro.shared.io import digest, file_hash, read_json


def verify_final_readiness(folder, config, record_path, source_hashes):
    disabled = 'Final test execution is disabled until an approved, matching readiness record is supplied'
    if not record_path:
        raise ValueError(disabled)
    path = Path(record_path)
    if not path.is_file():
        raise ValueError(disabled + ': readiness file not found')
    record = read_json(path)
    if record.get('status') != 'approved' or record.get('scope') != '400_factual_base_cases_both_orders':
        raise ValueError(disabled + ': approval or scope is incomplete')
    root = Path(folder)
    if root.name in ('dev', 'test'):
        root = root.parent
    if record.get('dataset_manifest_sha256') != file_hash(root / 'manifest.json'):
        raise ValueError('Final readiness dataset identity changed; review and freeze again')
    if record.get('config_digest') != digest(config):
        raise ValueError('Final readiness configuration changed; review and freeze again')
    if record.get('source_code_hashes') != source_hashes:
        raise ValueError('Final readiness source code changed; review and freeze again')
    for relative, expected in record.get('dataset_artifact_hashes', {}).items():
        if file_hash(root / relative) != expected:
            raise ValueError('Final readiness dataset artifact changed; review and freeze again')
    for evidence in record.get('supporting_artifacts', []):
        artifact = Path(evidence['path'])
        if not artifact.is_file() or file_hash(artifact) != evidence['sha256']:
            raise ValueError('Final readiness supporting evidence is missing or changed')
    for key in ('source_review', 'leakage_review', 'development_review'):
        review = record.get(key) or {}
        if review.get('status') not in ('complete', 'accepted_with_limitations') or not review.get('reviewer'):
            raise ValueError(f'Final readiness {key} is pending')
        evidence = Path(review.get('evidence_path', ''))
        if not evidence.is_file() or review.get('evidence_sha256') != file_hash(evidence):
            raise ValueError(f'Final readiness {key} evidence is missing or changed')
    development = record.get('development_run') or {}
    development_path = Path(development.get('manifest_path', ''))
    if not development_path.is_file() or development.get('manifest_sha256') != file_hash(development_path):
        raise ValueError('Final readiness development run evidence is missing or changed')
    previous = read_json(development_path)
    if previous.get('mode') != 'live' or previous.get('split', previous.get('dataset', {}).get('split')) != 'dev':
        raise ValueError('Final readiness requires a live development run')
    if previous.get('config') != config:
        raise ValueError('Final configuration does not match the reviewed development run')
    for name, value in source_hashes.items():
        if name.startswith(('ai_agents/', 'coordinator/')) or name in ('shared/benchmark_policy.py', 'shared/comparison.py'):
            if previous.get('code_hashes', {}).get(name) != value:
                raise ValueError('Judge or policy code changed after development; validate it on development cases first')
    checks_path = Path(record.get('automated_checks_path', ''))
    if not checks_path.is_file() or record.get('automated_checks_sha256') != file_hash(checks_path):
        raise ValueError('Final readiness automated checks are missing or changed')
    checks = read_json(checks_path)
    if checks.get('dataset_manifest_sha256') != record['dataset_manifest_sha256']:
        raise ValueError('Final readiness automated checks used a different dataset')
    correspondence = checks.get('source_correspondence') or {}
    if correspondence.get('recipes_checked', 0) < 1040 or correspondence.get('errors') != []:
        raise ValueError('Final readiness source correspondence has not passed')
    if checks.get('development_manifest_sha256') != development['manifest_sha256']:
        raise ValueError('Final readiness automated checks used a different development run')
    return {'path': str(path), 'sha256': file_hash(path), 'record': record}
