"""Cross-process stress proof for the metadata-only Agent JSONL writer."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from agents.common import trace
from config import ROOT, get_settings


WORKERS = 8
ROWS_PER_WORKER = 50
TEST_ROOT = get_settings().procureflow_data_root / 'phase4-trace-lock-test'
REPORT = ROOT / 'reports' / 'phase4' / 'trace-lock-stress.json'


def worker(index, rows):
    for row in range(rows):
        trace(f'P4LOCK-{index:02}-{row:04}', 'TraceStressAgent', 'TRACE_STRESS')


def verify():
    trace_path = TEST_ROOT / 'logs' / 'agents' / 'trace.jsonl'
    lock_path = trace_path.with_suffix(trace_path.suffix + '.lock')
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    for path in (trace_path, lock_path):
        if path.exists():
            path.unlink()
    environment = os.environ.copy()
    environment['PROCUREFLOW_DATA_ROOT'] = str(TEST_ROOT)
    processes = [subprocess.Popen([sys.executable, '-m', 'scripts.verify_trace_lock', '--worker', str(index),
                                   '--rows', str(ROWS_PER_WORKER)], cwd=ROOT, env=environment,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                 for index in range(WORKERS)]
    errors = []
    for process in processes:
        try:
            _, stderr = process.communicate(timeout=60)
            if process.returncode:
                errors.append(stderr.decode('utf-8', errors='replace')[-500:])
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            errors.append('worker timeout')
    lines = trace_path.read_text(encoding='utf-8').splitlines() if trace_path.exists() else []
    parsed = []
    malformed = 0
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
    expected = WORKERS * ROWS_PER_WORKER
    result = {'result': 'PASS' if not errors and malformed == 0 and len(parsed) == expected else 'FAIL',
              'workers': WORKERS, 'rows_per_worker': ROWS_PER_WORKER,
              'expected_rows': expected, 'actual_rows': len(parsed), 'malformed_rows': malformed,
              'worker_errors': errors}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=int)
    parser.add_argument('--rows', type=int, default=ROWS_PER_WORKER)
    args = parser.parse_args()
    if args.worker is not None:
        worker(args.worker, args.rows)
    else:
        raise SystemExit(0 if verify()['result'] == 'PASS' else 1)
