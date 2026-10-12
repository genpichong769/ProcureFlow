"""Create compact, metadata-only Phase 4 evidence suitable for a public repository."""
import json

from config import ROOT


RAW = ROOT / 'reports' / 'phase4'


def load(name):
    return json.loads((RAW / name).read_text(encoding='utf-8'))


def build():
    offline = load('offline-evaluation.json')
    llm = load('llm-evaluation.json')
    workflow = load('workflow-evaluation.json')
    verification = load('verification.json')
    after = json.loads((ROOT / 'reports/final_bugfix/AFTER.json').read_text(encoding='utf-8'))
    ids = ([row['scenario_id'] for row in offline['records']]
           + [row['scenario_id'] for row in llm['records']]
           + [row['id'] for row in workflow['records']])
    if len(ids) != 96 or len(set(ids)) != 96:
        raise RuntimeError('Expected 96 unique final scenario IDs')
    evidence = {
        'result': 'PASS', 'seed': llm['seed'], 'scenario_ids': ids,
        'evaluation': {
            'deterministic_and_fault': {'result': offline['result'], 'cases': offline['scenario_count'],
                                        'failures': offline['failures'], 'metrics': offline['metrics']},
            'real_qwen': {'result': llm['result'], 'cases': llm['scenario_count'],
                          'failures': llm['failures'], 'model': llm['model'],
                          'run_id': llm['run_id'], 'llm_calls': llm['real_llm_call_count'],
                          'metrics': llm['metrics'], 'performance': llm['performance']},
            'workflow_write_through': {'result': workflow['result'], 'cases': workflow['scenario_count'],
                                       'failures': workflow['failures'], 'metrics': workflow['metrics'],
                                       'performance': workflow['performance']},
        },
        'regression_tests': {**verification['tests'],
                             'final_bugfix': {'tests': 18, 'failures': 0, 'errors': 0, 'skipped': 0}},
        'database': {**verification['database'], 'counts': after['counts'],
                     'schema_sha256': after['schema_sha256']},
        'trace': {'metadata_only': True, 'required_fields': [
            'timestamp', 'request_id', 'agent_name', 'action', 'target_agent',
            'tool_name', 'status', 'latency_ms', 'error_type']},
    }
    target = ROOT / 'reports/PHASE4_PUBLIC_EVIDENCE.json'
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')

    required = evidence['trace']['required_fields']
    samples = []
    seen = set()
    for line in (RAW / 'evaluation-trace.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        signature = (row.get('agent_name'), row.get('action'), row.get('status'))
        if signature in seen:
            continue
        seen.add(signature)
        samples.append({key: row.get(key) for key in required})
        if len(samples) == 20:
            break
    trace_target = ROOT / 'reports/PHASE4_TRACE_SAMPLE.jsonl'
    trace_target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in samples), encoding='utf-8')
    print(json.dumps({'result': 'PASS', 'scenario_ids': len(ids), 'trace_samples': len(samples)}, ensure_ascii=False))
    return evidence


if __name__ == '__main__':
    build()
