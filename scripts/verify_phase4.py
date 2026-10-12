"""Final Phase4 evidence audit. It is read-only except for its JSON report."""
import ast
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import xml.etree.ElementTree as ET

import mysql.connector

from config import ROOT, get_settings
from scripts.docker_mysql import inspect, verify_mounts


FOLDER = ROOT / 'reports' / 'phase4'


def suite(path):
    root = ET.parse(path).getroot()
    if root.tag == 'testsuites':
        tests = sum(int(row.attrib.get('tests', 0)) for row in root)
        failures = sum(int(row.attrib.get('failures', 0)) for row in root)
        errors = sum(int(row.attrib.get('errors', 0)) for row in root)
        skipped = sum(int(row.attrib.get('skipped', 0)) for row in root)
    else:
        tests = int(root.attrib.get('tests', 0))
        failures = int(root.attrib.get('failures', 0))
        errors = int(root.attrib.get('errors', 0))
        skipped = int(root.attrib.get('skipped', 0))
    return {'tests': tests, 'failures': failures, 'errors': errors, 'skipped': skipped}


def imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.append(node.module or '')
    return values, tree


def is_listening(port):
    with socket.socket() as client:
        client.settimeout(.2)
        return client.connect_ex(('127.0.0.1', port)) == 0


def verify():
    settings = get_settings()
    before = json.loads((FOLDER / 'BEFORE.json').read_text(encoding='utf-8'))
    after = json.loads((FOLDER / 'AFTER.json').read_text(encoding='utf-8'))
    audit = json.loads((FOLDER / 'DATASET_AUDIT.json').read_text(encoding='utf-8'))
    offline = json.loads((FOLDER / 'offline-evaluation.json').read_text(encoding='utf-8'))
    llm = json.loads((FOLDER / 'llm-evaluation.json').read_text(encoding='utf-8'))
    workflow = json.loads((FOLDER / 'workflow-evaluation.json').read_text(encoding='utf-8'))
    initial = json.loads((FOLDER / 'initial-failures.json').read_text(encoding='utf-8'))
    trace_stress = json.loads((FOLDER / 'trace-lock-stress.json').read_text(encoding='utf-8'))
    restart = json.loads((ROOT / 'reports' / 'phase3' / 'restart-resume.json').read_text(encoding='utf-8'))
    tests = {name: suite(FOLDER / filename) for name, filename in (
        ('phase1', 'phase1-regression.xml'), ('phase2', 'phase2-regression.xml'),
        ('phase3', 'phase3-regression.xml'), ('phase4', 'phase4-tests.xml'))}

    docker = inspect()
    verify_mounts(docker)
    checkpoint = settings.require_persistent_path(settings.checkpoint_path)
    compose = subprocess.run(['docker', 'compose', 'config', '--quiet'], cwd=ROOT,
                             capture_output=True, text=True, check=False)

    classes = []
    forbidden_agent_imports = []
    forbidden_workflow_imports = []
    for folder in ('agents', 'a2a_server'):
        for path in (ROOT / folder).glob('*.py'):
            modules, tree = imports(path)
            classes.extend(node.name for node in ast.walk(tree)
                           if isinstance(node, ast.ClassDef) and node.name.endswith('Agent'))
            if folder == 'agents' and any(module.split('.')[0] in {'db', 'services', 'mysql'} for module in modules):
                forbidden_agent_imports.append(str(path.relative_to(ROOT)))
    for path in (ROOT / 'workflow').glob('*.py'):
        modules, _ = imports(path)
        if any(module.split('.')[0] in {'db', 'services', 'mysql'} for module in modules):
            forbidden_workflow_imports.append(str(path.relative_to(ROOT)))

    runtime = [path for folder in ('workflow', 'agents', 'a2a_server', 'api', 'services')
               for path in (ROOT / folder).glob('*.py')]
    coordinator_source = (ROOT / 'agents' / 'coordinator.py').read_text(encoding='utf-8')
    a2a_source = (ROOT / 'agents' / 'a2a_transport.py').read_text(encoding='utf-8')
    mcp_sources = [(ROOT / 'agents' / 'mcp_client.py').read_text(encoding='utf-8'),
                   (ROOT / 'workflow' / 'mcp_client.py').read_text(encoding='utf-8')]

    with mysql.connector.connect(**settings.connection_kwargs()) as connection:
        with connection.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute("SELECT COUNT(*) n FROM purchase_requests WHERE request_no LIKE 'P3TEST-%'")
            p3test = cursor.fetchone()['n']

    exported_trace = []
    for line in (FOLDER / 'evaluation-trace.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            exported_trace.append(json.loads(line))
    required_trace = {'timestamp', 'request_id', 'agent_name', 'action', 'target_agent',
                      'tool_name', 'status', 'latency_ms', 'error_type'}
    historical_bad_lines = 0
    live_trace = settings.logs_dir / 'agents' / 'trace.jsonl'
    for line in live_trace.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            historical_bad_lines += 1

    values = [settings.db_password.get_secret_value(), os.getenv('DASHSCOPE_API_KEY', '')]
    values = [value for value in values if len(value) >= 8]
    secret_findings = []
    scanned = 0
    excluded = {'.venv', '.runtime', '__pycache__', '.pytest_cache'}
    paths = [path for path in ROOT.rglob('*') if path.is_file()
             and not any(part in excluded for part in path.relative_to(ROOT).parts)
             and not path.name.startswith('.env')]
    paths += [path for path in settings.logs_dir.rglob('*') if path.is_file()]
    for path in paths:
        if path.suffix.lower() not in {'.py', '.md', '.json', '.jsonl', '.xml', '.log', '.txt', '.ini', '.yml', '.yaml', '.ps1'}:
            continue
        content = path.read_text(encoding='utf-8-sig', errors='replace')
        scanned += 1
        if any(value in content for value in values) or re.search(r'\bsk-[A-Za-z0-9_-]{20,}\b', content):
            secret_findings.append(str(path))

    ports = [5005, 5006, 5007, 5008, 8001, 8002, 8003, 8004, 8010, 5095]
    checks = {
        'phase1_85_passed': tests['phase1'] == {'tests': 85, 'failures': 0, 'errors': 0, 'skipped': 0},
        'phase2_52_passed': tests['phase2'] == {'tests': 52, 'failures': 0, 'errors': 0, 'skipped': 0},
        'phase3_18_passed': tests['phase3'] == {'tests': 18, 'failures': 0, 'errors': 0, 'skipped': 0},
        'phase4_12_passed': tests['phase4'] == {'tests': 12, 'failures': 0, 'errors': 0, 'skipped': 0},
        'independent_case_count_96': offline['scenario_count'] + llm['scenario_count'] + workflow['scenario_count'] == 96,
        'offline_sixty_pass': offline['result'] == 'PASS' and offline['scenario_count'] == 60,
        'real_llm_thirty_cap': llm['scenario_count'] == 30 and llm['real_llm_case_count'] == 30,
        'real_llm_all_pass_after_bugfix': llm['result'] == 'PASS' and llm['failures'] == []
                                          and llm['metrics']['requirement_parsing_accuracy']['numerator'] == 30,
        'workflow_six_pass': workflow['result'] == 'PASS' and workflow['scenario_count'] == 6,
        'initial_failures_preserved': initial['result'] == 'FAIL' and len(initial['failures']) >= 3,
        'database_sixteen_tables': len(after['tables']) == 16,
        'database_398869_rows': before['total_rows'] == after['total_rows'] == 398869,
        'database_counts_equal': before['counts'] == after['counts'],
        'database_content_hashes_equal': before['table_sha256'] == after['table_sha256'],
        'database_schema_equal': before['schema_sha256'] == after['schema_sha256'],
        'database_integrity_audit': audit['result'] == 'PASS',
        'no_p3test_rows': p3test == 0,
        'docker_healthy': docker['state']['Health']['Status'] == 'healthy',
        'docker_configured_bind': any(mount['Destination'] == '/var/lib/mysql' for mount in docker['mounts']),
        'compose_valid': compose.returncode == 0,
        'checkpoint_under_configured_root': checkpoint.exists()
                                            and checkpoint.resolve().is_relative_to(
                                                settings.procureflow_data_root.resolve()),
        'restart_resume_evidence': restart['result'] == 'PASS' and restart['different_process'],
        'exactly_four_agents': sorted(classes) == sorted([
            'BudgetAgent', 'SupplierSourcingAgent', 'ComplianceApprovalAgent', 'ProcurementCoordinatorAgent']),
        'single_langgraph_owner': sum('StateGraph(' in path.read_text(encoding='utf-8') for path in runtime) == 1,
        'no_agent_database_bypass': not forbidden_agent_imports,
        'no_workflow_database_bypass': not forbidden_workflow_imports,
        'a2a_is_network_transport': 'A2AClient' in a2a_source and 'send_task_async' in a2a_source
                                    and 'self.transport.call' in coordinator_source
                                    and 'agents.specialists' not in coordinator_source,
        'mcp_has_no_arbitrary_sql_tool': all('execute_sql' not in source for source in mcp_sources),
        'phase4_trace_valid': bool(exported_trace) and all(required_trace <= set(row) for row in exported_trace),
        'trace_cross_process_lock_stress': trace_stress['result'] == 'PASS'
                                           and trace_stress['actual_rows'] == trace_stress['expected_rows']
                                           and trace_stress['malformed_rows'] == 0,
        'no_secret_findings': not secret_findings,
        'runtime_ports_released': not any(is_listening(port) for port in ports),
        'dependencies_healthy': metadata.version('langgraph') == '0.6.11'
                                and metadata.version('langgraph-checkpoint-sqlite') == '2.0.11',
        'ignore_sensitive_runtime_files': all(token in (ROOT / '.gitignore').read_text(encoding='utf-8')
                                              for token in ('.env', '*.sqlite', 'reports/**/*-partial.json')),
        'no_unrelated_infrastructure': not any((ROOT / name).exists()
                                               for name in ('redis', 'kafka', 'milvus', 'celery', 'minio', 'rag')),
    }
    result = {
        'result': 'PASS' if all(checks.values()) else 'FAIL',
        'checks': checks, 'tests': tests,
        'limitations': [
            'High-risk monetary fields are now source-aligned deterministically; ambiguous amounts require clarification before dispatch.',
            f"{historical_bad_lines} malformed historical trace fragments remain in the append-only log; the final named-mutex stress proof wrote 400/400 valid rows.",
            'Token usage is unavailable because the validated gateway does not retain provider usage metadata.',
        ],
        'secret_scan': {'files_scanned': scanned, 'findings': secret_findings},
        'trace': {'phase4_rows': len(exported_trace), 'historical_malformed_lines': historical_bad_lines},
        'database': {'tables': len(after['tables']), 'rows': after['total_rows'],
                     'counts_equal': before['counts'] == after['counts'],
                     'content_hashes_equal': before['table_sha256'] == after['table_sha256'],
                     'schema_equal': before['schema_sha256'] == after['schema_sha256']},
        'architecture': {'agent_classes': sorted(classes), 'forbidden_agent_imports': forbidden_agent_imports,
                         'forbidden_workflow_imports': forbidden_workflow_imports},
        'docker': docker, 'checkpoint': {'path': str(checkpoint), 'bytes': checkpoint.stat().st_size},
    }
    (FOLDER / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': result['result'], 'checks': checks}, ensure_ascii=True))
    return result


if __name__ == '__main__':
    raise SystemExit(0 if verify()['result'] == 'PASS' else 1)
