import ast
import json

import mysql.connector

from config import ROOT, get_settings


REPORT = ROOT / 'reports'


def evidence():
    return json.loads((REPORT / 'PHASE4_PUBLIC_EVIDENCE.json').read_text(encoding='utf-8'))


def test_independent_scenario_set_is_fixed_and_unique():
    document = evidence()
    assert document['seed'] == 20261012
    assert len(document['scenario_ids']) == 96
    assert len(set(document['scenario_ids'])) == 96


def test_deterministic_evaluation_passed_all_sixty_cases():
    report = evidence()['evaluation']['deterministic_and_fault']
    assert report['result'] == 'PASS'
    assert report['cases'] == 60
    assert report['failures'] == []


def test_real_llm_result_passes_after_amount_validation_fix():
    report = evidence()['evaluation']['real_qwen']
    assert report['result'] == 'PASS'
    assert report['cases'] == 30
    assert 0 < report['llm_calls']
    assert report['metrics']['requirement_parsing_accuracy']['numerator'] == 30
    assert report['metrics']['requirement_parsing_accuracy']['denominator'] == 30
    assert report['failures'] == []


def test_new_workflow_evaluation_has_no_duplicate_order():
    report = evidence()['evaluation']['workflow_write_through']
    assert report['result'] == 'PASS'
    assert report['cases'] == 6
    assert report['metrics']['duplicate_purchase_order_rate'] == {
        'numerator': 0, 'denominator': 5, 'rate': 0.0}


def test_exactly_four_agent_classes_remain():
    classes = []
    for folder in ('agents', 'a2a_server'):
        for path in (ROOT / folder).glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            classes.extend(node.name for node in ast.walk(tree)
                           if isinstance(node, ast.ClassDef) and node.name.endswith('Agent'))
    assert sorted(classes) == sorted([
        'BudgetAgent', 'SupplierSourcingAgent', 'ComplianceApprovalAgent', 'ProcurementCoordinatorAgent'])


def test_langgraph_has_one_runtime_owner_and_no_database_import():
    runtime = [path for folder in ('workflow', 'agents', 'a2a_server', 'api', 'services')
               for path in (ROOT / folder).glob('*.py')]
    assert sum('StateGraph(' in path.read_text(encoding='utf-8') for path in runtime) == 1
    for path in (ROOT / 'workflow').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or '')
        assert not any(module.split('.')[0] in {'db', 'services', 'mysql'} for module in modules)


def test_coordinator_uses_a2a_and_does_not_import_specialists():
    coordinator = (ROOT / 'agents' / 'coordinator.py').read_text(encoding='utf-8')
    transport = (ROOT / 'agents' / 'a2a_transport.py').read_text(encoding='utf-8')
    assert 'self.transport.call' in coordinator
    assert 'agents.specialists' not in coordinator
    assert 'A2AClient' in transport and 'send_task_async' in transport


def test_mcp_boundaries_have_no_arbitrary_sql_tool():
    read_only = (ROOT / 'agents' / 'mcp_client.py').read_text(encoding='utf-8')
    workflow = (ROOT / 'workflow' / 'mcp_client.py').read_text(encoding='utf-8')
    assert 'execute_sql' not in read_only
    assert 'execute_sql' not in workflow
    for path in (ROOT / 'agents').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or '')
        assert not any(module.split('.')[0] in {'db', 'services', 'mysql'} for module in modules)


def test_checkpoint_is_under_configured_persistent_root():
    checkpoint = get_settings().checkpoint_path.resolve()
    assert checkpoint.is_relative_to(get_settings().procureflow_data_root.resolve())
    assert checkpoint.is_file() and checkpoint.stat().st_size > 0


def test_database_returned_to_frozen_baseline():
    settings = get_settings()
    connection = mysql.connector.connect(**settings.connection_kwargs())
    try:
        with connection.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute('SHOW TABLES')
            assert len(cursor.fetchall()) == 16
            cursor.execute("SELECT COUNT(*) n FROM purchase_requests WHERE request_no LIKE 'P3TEST-%'")
            assert cursor.fetchone()['n'] == 0
            total = 0
            for table in json.loads((ROOT / 'reports/PHASE4_PUBLIC_EVIDENCE.json').read_text(encoding='utf-8'))['database']['counts']:
                cursor.execute(f'SELECT COUNT(*) n FROM `{table}`')
                total += cursor.fetchone()['n']
            assert total == 398869
    finally:
        connection.close()


def test_phase4_trace_export_is_valid_metadata_only_jsonl():
    required = {'timestamp', 'request_id', 'agent_name', 'action', 'target_agent',
                'tool_name', 'status', 'latency_ms', 'error_type'}
    rows = [json.loads(line) for line in (REPORT / 'PHASE4_TRACE_SAMPLE.jsonl').read_text(encoding='utf-8').splitlines()
            if line.strip()]
    assert rows
    assert all(required <= set(row) for row in rows)
    assert all('prompt' not in row and 'password' not in row and 'api_key' not in row for row in rows)


def test_performance_statistics_have_real_samples():
    document = evidence()['evaluation']
    llm = document['real_qwen']['performance']['request_end_to_end']
    workflow = document['workflow_write_through']['performance']
    assert llm['samples'] == 30 and llm['p50_ms'] > 0 and llm['p95_ms'] >= llm['p50_ms']
    assert workflow['samples'] == 6 and workflow['p50_ms'] > 0 and workflow['p95_ms'] >= workflow['p50_ms']
