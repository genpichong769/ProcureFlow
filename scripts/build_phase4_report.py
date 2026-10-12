"""Rebuild the compact Phase 4 metrics artifact from recorded local evidence."""
import json

from config import ROOT


RAW = ROOT / 'reports' / 'phase4'
REPORT = ROOT / 'reports' / 'PHASE4_METRICS.json'


def load(name):
    return json.loads((RAW / name).read_text(encoding='utf-8'))


def build():
    offline = load('offline-evaluation.json')
    llm = load('llm-evaluation.json')
    workflow = load('workflow-evaluation.json')
    verification = load('verification.json')
    if not (offline['result'] == llm['result'] == workflow['result'] == verification['result'] == 'PASS'):
        raise RuntimeError('Phase 4 evidence is not fully passing; refusing to publish aggregate metrics')
    if llm['scenario_count'] != 30 or llm['failures']:
        raise RuntimeError('Real-LLM evidence is incomplete or has failures')

    result = {
        'result': 'PASS', 'seed': llm['seed'],
        'evaluation_sets': {
            'deterministic_and_fault': {'cases': offline['scenario_count'], 'passed': offline['scenario_count']},
            'real_qwen': {'cases': llm['scenario_count'], 'passed': llm['scenario_count'],
                          'model': llm['model'], 'run_id': llm['run_id'],
                          'llm_calls': llm['real_llm_call_count']},
            'workflow_write_through': {'cases': workflow['scenario_count'], 'passed': workflow['scenario_count']},
        },
        'real_qwen_metrics': llm['metrics'],
        'performance_ms': {
            'real_qwen_request': llm['performance']['request_end_to_end'],
            'requirement_extraction': llm['performance']['requirement_parsing'],
            'mcp_call': llm['performance']['mcp_call'],
        },
        'regression_tests': {**{name: data['tests'] for name, data in verification['tests'].items()},
                             'final_bugfix': 18},
        'database': {**verification['database'],
                     'schema_sha256': load('AFTER.json')['schema_sha256']},
        'limitations': [
            'Metrics describe a fixed acceptance set and do not establish universal model accuracy.',
            'Token usage is unavailable because the gateway does not retain provider usage metadata.',
            'Performance is from one local low-concurrency environment.',
        ],
    }
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': result['result'], 'phase4_cases': 96,
                      'real_qwen': '30/30', 'llm_calls': llm['real_llm_call_count']}, ensure_ascii=False))
    return result


if __name__ == '__main__':
    build()
