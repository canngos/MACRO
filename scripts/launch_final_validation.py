"""Launch an approved frozen 400-case DeepSeek run in the background on Windows."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from macro.evaluation.readiness import verify_final_readiness
from macro.evaluation.runner import experiment_plan, source_code_hashes
from macro.shared.config import api_key
from macro.shared.io import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--readiness', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--dataset', default='data/benchmark-v2')
    parser.add_argument('--max-calls', type=int, default=19200)
    args = parser.parse_args()
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.run_id):
        raise ValueError('Invalid run ID')
    config = read_json(args.config)
    if config.get('provider') != 'deepseek':
        raise ValueError('This launcher is only for the frozen DeepSeek experiment')
    freeze = verify_final_readiness(args.dataset, config, args.readiness, source_code_hashes())
    plan = experiment_plan(args.dataset, 400, config, split='test')
    if args.max_calls < plan['total_initial_calls']:
        raise ValueError('Request cap cannot cover all initial requests')
    run_dir = Path('results') / args.run_id
    if run_dir.exists():
        raise ValueError('Run ID already exists; inspect it before deciding whether to resume')
    # Authentication/connectivity check only; /models makes no generation requests.
    from openai import OpenAI
    try:
        client = OpenAI(api_key=api_key(config), base_url=config['base_url'], max_retries=0, timeout=20)
        client.models.list()
        client.close()
    except Exception as exc:
        print(json.dumps({'launch_status': 'not_started', 'error_type': type(exc).__name__,
                          'http_status': getattr(exc, 'status_code', None)}))
        return 2
    command = [sys.executable, '-u', '-m', 'macro', 'run', '--config', args.config,
               '--cases', args.dataset, '--split', 'test', '--limit', '400', '--allow-paid-api',
               '--max-calls', str(args.max_calls), '--run-id', args.run_id,
               '--final-readiness', args.readiness]
    run_dir.mkdir(parents=True)
    stdout_path, stderr_path = run_dir / 'terminal.log', run_dir / 'terminal-errors.log'
    with stdout_path.open('w', encoding='utf-8') as stdout, stderr_path.open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                                   cwd=Path.cwd(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    receipt = {'launch_status': 'started', 'run_id': args.run_id, 'pid': process.pid,
               'started_utc': datetime.now(timezone.utc).isoformat(), 'readiness_sha256': freeze['sha256'],
               'command': command, 'initial_requests': plan['total_initial_calls'],
               'max_calls': args.max_calls, 'stdout': str(stdout_path), 'stderr': str(stderr_path)}
    write_json(run_dir / 'launch.json', receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
