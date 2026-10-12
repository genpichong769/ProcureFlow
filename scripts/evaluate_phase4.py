"""Phase4 independent evaluation: 60 deterministic/fault cases plus 30 real-LLM cases.

Deterministic proposal cases use real A2A, MCP, rules and the frozen MySQL data, but an
evaluation-only fixed tool planner. LLM cases use the deployed four-agent stack and Qwen.
The SQL oracle is outside runtime agents and supplies independent expected answers.
"""
import argparse
import asyncio
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import time
from time import perf_counter
from uuid import uuid4

from agents.a2a_transport import A2ATransport
from agents.common import AgentFailure
from agents.coordinator import ProcurementCoordinatorAgent
from agents.mcp_client import ReadOnlyMCP
from agents.specialists import BudgetAgent
from config import ROOT, get_settings
from db.connection import Database
from scripts.evaluate_phase2 import Oracle, parse_matches
from scripts.phase2_stack import stack as llm_stack
from scripts.phase4_eval_support import DeterministicGateway
from scripts.phase4_offline_stack import stack as offline_stack
from services.budget_service import BudgetService


SEED = 20261012
GENERATED = get_settings().require_persistent_path(get_settings().generated_dir / 'phase4' / 'scenarios.json')
REPORT_DIR = ROOT / 'reports' / 'phase4'
OFFLINE_REPORT = REPORT_DIR / 'offline-evaluation.json'
LLM_REPORT = REPORT_DIR / 'llm-evaluation.json'
TRACE_REPORT = REPORT_DIR / 'evaluation-trace.jsonl'


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def metric(records, key):
    values = [bool(row['checks'][key]) for row in records if key in row.get('checks', {})]
    return {'numerator': sum(values), 'denominator': len(values),
            'rate': sum(values) / len(values) if values else None}


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(float(v) for v in values)
    index = max(0, min(len(values) - 1, int((len(values) - 1) * fraction + .999999)))
    return round(values[index], 3)


def latency_summary(values):
    return {'samples': len(values), 'p50_ms': percentile(values, .50), 'p95_ms': percentile(values, .95),
            'min_ms': round(min(values), 3) if values else None,
            'max_ms': round(max(values), 3) if values else None}


def traces_for(prefixes):
    path = get_settings().logs_dir / 'agents' / 'trace.jsonl'
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # Preserve historical malformed rows for the failure report, but do
            # not let an unrelated old line prevent filtering this run by ID.
            continue
        if any(str(row.get('request_id', '')).startswith(prefix) for prefix in prefixes):
            rows.append(row)
    return rows


def trace_metrics(rows):
    output = {}
    for name, action in [('a2a_call_success_rate', 'A2A_CALL'), ('mcp_tool_success_rate', 'MCP_CALL')]:
        selected = [row for row in rows if row.get('action') == action]
        passed = sum(row.get('status') == 'SUCCESS' for row in selected)
        output[name] = {'numerator': passed, 'denominator': len(selected),
                        'rate': passed / len(selected) if selected else None}
    return output


def expected_for(oracle, scenario):
    if scenario.get('expected_status') == 'ERROR':
        return {'status': 'ERROR'}
    if scenario.get('kind') == 'missing_required_fields':
        return {'status': 'NEED_MORE_INFORMATION'}
    return oracle.expected({'kind': scenario['kind'], 'requirement': scenario['requirement']})


def compare_proposal(oracle, scenario, actual):
    expected = expected_for(oracle, scenario)
    checks = {'expected_outcome': actual.get('status') == expected['status']}
    if scenario.get('expected_fields') is not None:
        checks['requirement_parsing_accuracy'] = parse_matches(actual.get('requirement') or {}, scenario['expected_fields'])
    if expected.get('budget') is not None:
        received = actual.get('budget_result') or {}
        checks['budget_check_accuracy'] = all(
            key in received and (Decimal(str(received[key])) == value if isinstance(value, Decimal) else received[key] == value)
            for key, value in expected['budget'].items())
    if expected.get('candidates') is not None:
        received_all = actual.get('all_candidates', [])
        received_good = actual.get('qualified_candidates', [])
        checks['supplier_filtering_accuracy'] = (
            {row['id'] for row in expected['candidates']} == {row['quote_id'] for row in received_all}
            and {row['id'] for row in expected['qualified']} == {row['quote_id'] for row in received_good}
            and all(oracle.facts_match(row, scenario['requirement']) for row in received_all))
    if expected.get('compliance'):
        def normalized(row):
            return (row['supplier_id'], row['compliance_passed'], row['required_quote_count'], tuple(row['approval_chain']))
        checks['compliance_accuracy'] = sorted(map(normalized, actual.get('compliance_results', []))) == sorted(
            map(normalized, expected['compliance']))
    if expected.get('winner'):
        winner = actual.get('recommended_supplier') or {}
        checks['recommendation_validity'] = (
            winner.get('quote_id') == expected['winner']
            and oracle.facts_match(winner, scenario['requirement'])
            and actual.get('compliance_result', {}).get('compliance_passed') is True)
        reason = actual.get('recommendation_reason', '')
        checks['natural_language_explanation_grounding'] = (
            winner.get('supplier_name', '') in reason and str(winner.get('supplier_code', '')) in reason
            and str(winner.get('final_score', '')) in reason)
    if scenario.get('excluded_quote_id') is not None:
        checks['expired_quote_excluded'] = scenario['excluded_quote_id'] not in {
            row['quote_id'] for row in actual.get('all_candidates', [])}
    return checks


def ready_candidates(oracle, product_ids, count, quantities=(2, 5, 10, 20, 30)):
    found = []
    for product_id in product_ids:
        product = oracle.products[f'PRD{product_id:05}']
        for quantity in quantities:
            department = f'DEP{((product_id + quantity) % 25) + 6:03}'
            amount = (product['reference_price'] * Decimal(quantity) * Decimal('2.20')).quantize(Decimal('.01'))
            requirement = {'department_code': department, 'product_code': product['product_code'],
                           'quantity': quantity, 'max_total_amount': str(amount), 'max_delivery_days': 60}
            try:
                expected = oracle.expected({'kind': 'normal', 'requirement': requirement})
            except Exception:
                continue
            if expected['status'] == 'READY_FOR_APPROVAL':
                found.append(requirement)
                break
        if len(found) == count:
            return found
    raise RuntimeError(f'Could not build {count} independent READY cases')


def score_gap(oracle, rows):
    if len(rows) < 2:
        return None
    settings = get_settings()
    weights = [Decimal(str(getattr(settings, f'score_{name}_weight')))
               for name in ('price', 'delivery', 'on_time', 'quality')]
    minimum_price = min(row['unit_price'] for row in rows)
    minimum_days = min(row['delivery_days'] for row in rows)
    scores = []
    for row in rows:
        supplier = oracle.suppliers[row['supplier_id']]
        values = [minimum_price / row['unit_price'] * 100, Decimal(minimum_days) / row['delivery_days'] * 100,
                  supplier['on_time_rate'] * 100, supplier['quality_rate'] * 100]
        scores.append(sum(weight * value for weight, value in zip(weights, values)))
    scores.sort(reverse=True)
    return (scores[0] - scores[1]).quantize(Decimal('.000001'))


def build_scenarios():
    oracle = Oracle()
    rng = random.Random(SEED)
    product_ids = list(range(501, 4901))
    rng.shuffle(product_ids)
    offline = []
    llm = []

    def add_offline(kind, requirement, **extra):
        offline.append({'id': f'P4-O{len(offline)+1:03}', 'kind': kind, 'requirement': requirement, **extra})

    normal = ready_candidates(oracle, product_ids, 10)
    for requirement in normal:
        add_offline('normal_purchase', requirement)

    for index in range(6):
        requirement = dict(normal[index])
        available = oracle.budgets[requirement['department_code']]['total_budget'] \
            - oracle.budgets[requirement['department_code']]['used_budget'] \
            - oracle.budgets[requirement['department_code']]['reserved_budget']
        requirement['max_total_amount'] = str(available + Decimal('.01'))
        add_offline('insufficient_budget', requirement)

    for index in range(6):
        requirement = dict(normal[(index + 2) % len(normal)])
        budget = oracle.budgets[requirement['department_code']]
        available = budget['total_budget'] - budget['used_budget'] - budget['reserved_budget']
        requirement['max_total_amount'] = str(available)
        add_offline('budget_exact_boundary', requirement)

    exact_count = 0
    for product_id in product_ids[100:]:
        requirement = {'department_code': f'DEP{(product_id % 25) + 6:03}', 'product_code': f'PRD{product_id:05}',
                       'quantity': 1, 'max_total_amount': '999999.00', 'max_delivery_days': 120}
        rows = oracle.candidates(requirement)
        if not rows:
            continue
        quote = min(rows, key=lambda row: (row['unit_price'], row['id']))
        requirement['max_total_amount'] = str(quote['unit_price'])
        if oracle.expected({'kind': 'quote_exact', 'requirement': requirement})['status'] == 'READY_FOR_APPROVAL':
            add_offline('quote_equals_budget', requirement, boundary_quote_id=quote['id'])
            exact_count += 1
        if exact_count == 6:
            break
    if exact_count != 6:
        raise RuntimeError('Could not build quote/budget boundary cases')

    stock_count = 0
    for product_id in product_ids[300:]:
        product = oracle.products[f'PRD{product_id:05}']
        for quote in oracle.byproduct[product['id']]:
            supplier = oracle.suppliers[quote['supplier_id']]
            quantity = quote['available_quantity']
            if not 1 <= quantity <= 80 or supplier['status'] != 'ACTIVE' or not oracle.valid_quals(supplier['id']):
                continue
            requirement = {'department_code': f'DEP{(product_id % 25) + 6:03}', 'product_code': product['product_code'],
                           'quantity': quantity, 'max_total_amount': str(quote['unit_price'] * quantity),
                           'max_delivery_days': max(quote['delivery_days'], 30)}
            expected = oracle.expected({'kind': 'stock_exact', 'requirement': requirement})
            if expected['status'] == 'READY_FOR_APPROVAL' and quote['id'] in {row['id'] for row in expected['candidates']}:
                add_offline('stock_exact_boundary', requirement, boundary_quote_id=quote['id'])
                stock_count += 1
                break
        if stock_count == 6:
            break
    if stock_count != 6:
        raise RuntimeError('Could not build stock boundary cases')

    expired_count = 0
    for quote in oracle.quotes:
        if not (quote['valid_until'] < date.today() or quote['status'] != 'ACTIVE'):
            continue
        product = next(row for row in oracle.products.values() if row['id'] == quote['product_id'])
        requirement = {'department_code': f'DEP{(product['id'] % 25) + 6:03}', 'product_code': product['product_code'],
                       'quantity': 1, 'max_total_amount': str(product['reference_price'] * Decimal('3')),
                       'max_delivery_days': 120}
        expected = oracle.expected({'kind': 'expired_filter', 'requirement': requirement})
        if expected['status'] == 'READY_FOR_APPROVAL' and quote['id'] not in {row['id'] for row in expected['candidates']}:
            add_offline('expired_quote_filter', requirement, excluded_quote_id=quote['id'])
            expired_count += 1
        if expired_count == 4:
            break
    if expired_count != 4:
        raise RuntimeError('Could not build expired quote cases')

    invalid_count = 0
    for supplier_id, supplier in oracle.suppliers.items():
        if supplier['status'] == 'ACTIVE' and oracle.valid_quals(supplier_id):
            continue
        quote = next((row for row in oracle.quotes if row['supplier_id'] == supplier_id), None)
        if quote is None:
            continue
        product = next(row for row in oracle.products.values() if row['id'] == quote['product_id'])
        requirement = {'department_code': f'DEP{(product['id'] % 25) + 6:03}', 'product_code': product['product_code'],
                       'quantity': 1, 'max_total_amount': str(product['reference_price'] * Decimal('3')),
                       'max_delivery_days': 120, 'supplier_id': supplier_id, 'category': product['category']}
        if oracle.expected({'kind': 'invalid_supplier', 'requirement': requirement})['status'] == 'COMPLIANCE_FAILED':
            add_offline('blacklist_or_qualification_failure', requirement)
            invalid_count += 1
        if invalid_count == 4:
            break
    if invalid_count != 4:
        raise RuntimeError('Could not build invalid supplier cases')

    none_count = 0
    for requirement in ready_candidates(oracle, product_ids[500:], 20):
        requirement = dict(requirement)
        requirement['max_delivery_days'] = 1
        if oracle.expected({'kind': 'no_supplier', 'requirement': requirement})['status'] == 'NO_SUPPLIER':
            add_offline('no_valid_supplier', requirement)
            none_count += 1
        if none_count == 4:
            break
    if none_count != 4:
        raise RuntimeError('Could not build no-supplier cases')

    close = []
    for requirement in ready_candidates(oracle, product_ids[800:], 80):
        expected = oracle.expected({'kind': 'close_score', 'requirement': requirement})
        gap = score_gap(oracle, expected['qualified'])
        if gap is not None:
            close.append((gap, requirement))
    for gap, requirement in sorted(close, key=lambda item: item[0])[:4]:
        add_offline('close_supplier_scores', requirement, score_gap=str(gap))

    for index in range(2):
        requirement = dict(normal[index])
        requirement['department_code'] = f'DEP9{index+8:02}'
        add_offline('nonexistent_department', requirement, expected_status='ERROR')
    for index in range(2):
        requirement = dict(normal[index + 2])
        requirement['product_code'] = f'PRD9{index+8:04}'
        add_offline('nonexistent_product', requirement, expected_status='ERROR')

    if len(offline) != 54:
        raise RuntimeError(f'Expected 54 proposal cases, got {len(offline)}')

    llm_sources = ready_candidates(oracle, product_ids[1200:], 24)
    templates = [
        '{department_code} 要买 {quantity} 件 {product_code}，总预算封顶 {max_total_amount} 元，最迟 {max_delivery_days} 天到。',
        '麻烦给 {department_code} 办一下：{product_code} 来 {quantity} 个，钱别超过 {max_total_amount}，{max_delivery_days} 天内送到。',
        '采购申请：部门={department_code}；物料={product_code}；数量={quantity}；总额上限={max_total_amount}元；交期={max_delivery_days}天。',
    ]
    for index in range(16):
        requirement = llm_sources[index]
        text = templates[index % len(templates)].format(**requirement)
        kind = 'colloquial_requirement' if index % 3 == 1 else 'normal_natural_language'
        llm.append({'id': f'P4-L{len(llm)+1:03}', 'kind': kind, 'text': text,
                    'requirement': requirement, 'expected_fields': requirement})
    for index in range(4):
        requirement = llm_sources[16 + index]
        product = oracle.products[requirement['product_code']]
        text = (f"{requirement['department_code']} 想采购{product['product_name']}，也就是系统物料号"
                f"{requirement['product_code']}，要{requirement['quantity']}件，总预算{requirement['max_total_amount']}元，"
                f"{requirement['max_delivery_days']}天内到货。")
        llm.append({'id': f'P4-L{len(llm)+1:03}', 'kind': 'product_alias_with_code', 'text': text,
                    'requirement': requirement, 'expected_fields': requirement})
    for index in range(4):
        source = llm_sources[20 + index]
        requirement = {'department_code': source['department_code'], 'product_code': source['product_code'],
                       'quantity': None, 'max_total_amount': None, 'max_delivery_days': None}
        text = f"{source['department_code']} 近期想补一些 {source['product_code']}，数量、预算和到货时间还没定。"
        llm.append({'id': f'P4-L{len(llm)+1:03}', 'kind': 'missing_required_fields', 'text': text,
                    'requirement': requirement, 'expected_fields': requirement})
    for index in range(3):
        requirement = dict(llm_sources[index])
        budget = oracle.budgets[requirement['department_code']]
        available = budget['total_budget'] - budget['used_budget'] - budget['reserved_budget']
        requirement['max_total_amount'] = str(available + Decimal('100.00'))
        text = templates[index].format(**requirement)
        llm.append({'id': f'P4-L{len(llm)+1:03}', 'kind': 'natural_language_no_budget', 'text': text,
                    'requirement': requirement, 'expected_fields': requirement})
    for index in range(3):
        requirement = dict(llm_sources[index + 3])
        if index % 2:
            requirement['department_code'] = f'DEP99{index}'
        else:
            requirement['product_code'] = f'PRD99{index:03}'
        text = templates[index].format(**requirement)
        llm.append({'id': f'P4-L{len(llm)+1:03}', 'kind': 'unknown_entity', 'text': text,
                    'requirement': requirement, 'expected_fields': requirement, 'expected_status': 'ERROR'})
    if len(llm) != 30:
        raise RuntimeError(f'Expected 30 LLM cases, got {len(llm)}')

    resilience = [
        {'id': 'P4-R001', 'kind': 'a2a_unavailable'},
        {'id': 'P4-R002', 'kind': 'a2a_timeout'},
        {'id': 'P4-R003', 'kind': 'mcp_temporarily_unavailable'},
        {'id': 'P4-R004', 'kind': 'database_connection_interrupted'},
        {'id': 'P4-R005', 'kind': 'arbitrary_sql_forbidden'},
        {'id': 'P4-R006', 'kind': 'invalid_tool_parameters'},
    ]
    document = {'seed': SEED, 'created_from_frozen_database': True, 'offline_proposal_cases': offline,
                'resilience_cases': resilience, 'llm_cases': llm}
    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    if GENERATED.exists():
        existing = json.loads(GENERATED.read_text(encoding='utf-8'))
        if existing != document:
            raise RuntimeError('Frozen Phase4 scenario file differs from reproducible builder output')
    else:
        json_write(GENERATED, document)
    return document


async def run_proposal_cases(cases, oracle, coordinator, run_id, concurrency):
    records = []
    semaphore = asyncio.Semaphore(concurrency)

    async def one(scenario):
        async with semaphore:
            request_id = f'{run_id}-{scenario['id']}'
            start = perf_counter()
            payload = {'request_id': request_id, 'requirement': scenario['requirement']}
            proposal = (await coordinator.run(payload)).model_dump(mode='json')
            checks = compare_proposal(oracle, scenario, proposal)
            row = {'scenario_id': scenario['id'], 'kind': scenario['kind'], 'request_id': request_id,
                   'latency_ms': round((perf_counter() - start) * 1000, 3), 'actual_status': proposal['status'],
                   'checks': checks, 'proposal': proposal}
            records.append(row)
            print(scenario['id'], scenario['kind'], proposal['status'], 'PASS' if all(checks.values()) else 'FAIL', flush=True)

    await asyncio.gather(*(one(scenario) for scenario in cases))
    return sorted(records, key=lambda row: row['scenario_id'])


def wait_port(port, deadline=10):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        with socket.socket() as sock:
            sock.settimeout(.2)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return
        time.sleep(.1)
    raise RuntimeError(f'Port {port} did not open')


async def run_resilience(cases, run_id):
    import agents.a2a_transport as a2a_module
    import agents.mcp_client as mcp_module
    records = []
    settings = get_settings()

    async def record(scenario, operation):
        start = perf_counter()
        try:
            detail = await operation()
            passed = bool(detail.get('passed'))
        except Exception as exc:
            detail = {'passed': False, 'unexpected_type': type(exc).__name__}
            passed = False
        row = {'scenario_id': scenario['id'], 'kind': scenario['kind'],
               'latency_ms': round((perf_counter() - start) * 1000, 3),
               'checks': {'expected_failure_handling': passed}, 'detail': detail}
        records.append(row)
        print(scenario['id'], scenario['kind'], 'PASS' if passed else 'FAIL', flush=True)

    async def a2a_unavailable():
        original = a2a_module.get_settings
        bad = settings.model_copy(update={'a2a_budget_port': 5094, 'agent_max_retries': 0, 'agent_timeout_seconds': 1.0})
        a2a_module.get_settings = lambda: bad
        try:
            await A2ATransport().call('budget', {'request_id': f'{run_id}-P4-R001',
                                                'department_code': 'DEP001', 'requested_amount': '1.00'})
        except AgentFailure as exc:
            return {'passed': exc.code in {'BUDGET_AGENT_UNAVAILABLE', 'A2A_TIMEOUT'}, 'error_type': exc.code,
                    'classification': 'closed endpoint can surface as connect timeout in python-a2a'}
        finally:
            a2a_module.get_settings = original
        return {'passed': False, 'error_type': None}

    async def a2a_timeout():
        log = get_settings().require_persistent_path(get_settings().logs_dir / 'phase4' / 'slow-a2a.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        handle = log.open('w', encoding='utf-8')
        proc = subprocess.Popen([sys.executable, '-m', 'scripts.phase4_slow_a2a_server'], cwd=ROOT,
                                stdout=handle, stderr=handle,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            await asyncio.to_thread(wait_port, 5095)
            original = a2a_module.get_settings
            bad = settings.model_copy(update={'a2a_budget_port': 5095, 'agent_max_retries': 0,
                                              'agent_timeout_seconds': .25})
            a2a_module.get_settings = lambda: bad
            try:
                await A2ATransport().call('budget', {'request_id': f'{run_id}-P4-R002',
                                                    'department_code': 'DEP001', 'requested_amount': '1.00'})
            except AgentFailure as exc:
                return {'passed': exc.code == 'A2A_TIMEOUT', 'error_type': exc.code}
            finally:
                a2a_module.get_settings = original
            return {'passed': False, 'error_type': None}
        finally:
            if proc.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            handle.close()

    async def mcp_unavailable():
        original = mcp_module.get_settings
        bad = settings.model_copy(update={'mcp_budget_port': 8091, 'agent_max_retries': 0, 'mcp_timeout_seconds': 1.0})
        mcp_module.get_settings = lambda: bad
        try:
            await BudgetAgent(llm=DeterministicGateway()).run(
                {'request_id': f'{run_id}-P4-R003', 'department_code': 'DEP001', 'requested_amount': '1.00'})
        except AgentFailure as exc:
            return {'passed': exc.code == 'MCP_UNAVAILABLE', 'error_type': exc.code}
        finally:
            mcp_module.get_settings = original
        return {'passed': False, 'error_type': None}

    async def database_interrupted():
        bad = settings.model_copy(update={'db_port': 3399, 'db_pool_size': 1})
        start = perf_counter()
        try:
            await asyncio.to_thread(BudgetService(Database(bad)).get_department_budget, 'DEP001')
        except Exception as exc:
            elapsed = perf_counter() - start
            return {'passed': elapsed < 12 and type(exc).__name__ in {'DatabaseError', 'InterfaceError', 'PoolError'},
                    'error_type': type(exc).__name__, 'bounded_seconds': round(elapsed, 3)}
        return {'passed': False, 'error_type': None}

    async def sql_forbidden():
        try:
            await ReadOnlyMCP('budget', f'{run_id}-P4-R005', 'BudgetAgent').call('execute_sql', {'sql': 'SELECT 1'})
        except AgentFailure as exc:
            return {'passed': exc.code == 'FORBIDDEN_TOOL', 'error_type': exc.code}
        return {'passed': False, 'error_type': None}

    async def invalid_parameters():
        try:
            await BudgetAgent(llm=DeterministicGateway()).run(
                {'request_id': f'{run_id}-P4-R006', 'department_code': 'DEP001', 'requested_amount': '-1'})
        except Exception as exc:
            return {'passed': type(exc).__name__ == 'ValidationError', 'error_type': type(exc).__name__}
        return {'passed': False, 'error_type': None}

    operations = [a2a_unavailable, a2a_timeout, mcp_unavailable, database_interrupted, sql_forbidden, invalid_parameters]
    for scenario, operation in zip(cases, operations):
        await record(scenario, operation)
    return records


def run_offline(document):
    oracle = Oracle()
    run_id = 'P4OFF-' + uuid4().hex[:10]

    async def execute():
        with offline_stack():
            coordinator = ProcurementCoordinatorAgent(llm=DeterministicGateway())
            proposals = await run_proposal_cases(document['offline_proposal_cases'], oracle, coordinator, run_id, 3)
            resilience = await run_resilience(document['resilience_cases'], run_id)
            return proposals, resilience

    proposals, resilience = asyncio.run(execute())
    records = proposals + resilience
    traces = traces_for([run_id])
    metrics = {name: metric(records, key) for name, key in (
        ('budget_check_accuracy', 'budget_check_accuracy'),
        ('supplier_filtering_accuracy', 'supplier_filtering_accuracy'),
        ('compliance_accuracy', 'compliance_accuracy'),
        ('recommendation_validity', 'recommendation_validity'))}
    metrics.update(trace_metrics(traces))
    report = {'result': 'PASS' if all(all(row['checks'].values()) for row in records) else 'FAIL',
              'run_id': run_id, 'completed_at': utcnow(), 'evaluation_mode': 'DETERMINISTIC_OFFLINE',
              'seed': SEED, 'scenario_count': len(records),
              'categories': dict(Counter(row['kind'] for row in records)), 'metrics': metrics,
              'performance': {'proposal_end_to_end': latency_summary([row['latency_ms'] for row in proposals]),
                              'resilience_probe': latency_summary([row['latency_ms'] for row in resilience])},
              'failures': [row['scenario_id'] for row in records if not all(row['checks'].values())],
              'records': records}
    json_write(OFFLINE_REPORT, report)
    TRACE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    TRACE_REPORT.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in traces), encoding='utf-8')
    print(json.dumps({'result': report['result'], 'scenario_count': len(records), 'metrics': metrics}, ensure_ascii=False))
    return report


def run_llm(document):
    oracle = Oracle()
    partials = sorted(REPORT_DIR.glob('P4LLM-*-partial.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    resume = None
    if partials:
        candidate = json.loads(partials[0].read_text(encoding='utf-8'))
        if 0 < len(candidate.get('records', [])) < len(document['llm_cases']):
            resume = candidate
    run_id = resume['run_id'] if resume else 'P4LLM-' + uuid4().hex[:10]

    async def execute():
        with llm_stack():
            records = list(resume['records']) if resume else []
            completed = {row['scenario_id'] for row in records}
            if completed:
                print(f'Resuming {run_id}: {len(completed)} completed, '
                      f'{len(document["llm_cases"])-len(completed)} remaining', flush=True)
            semaphore = asyncio.Semaphore(2)

            async def one(scenario):
                async with semaphore:
                    request_id = f'{run_id}-{scenario['id']}'
                    start = perf_counter()
                    try:
                        proposal = await A2ATransport().call('procurement', {'request_id': request_id, 'text': scenario['text']})
                    except AgentFailure as exc:
                        proposal = {'status': 'ERROR', 'error_type': exc.code}
                    checks = compare_proposal(oracle, scenario, proposal)
                    row = {'scenario_id': scenario['id'], 'kind': scenario['kind'], 'request_id': request_id,
                           'latency_ms': round((perf_counter() - start) * 1000, 3), 'actual_status': proposal['status'],
                           'checks': checks, 'proposal': proposal}
                    records.append(row)
                    partial = {'run_id': run_id, 'records': sorted(records, key=lambda item: item['scenario_id'])}
                    json_write(REPORT_DIR / f'{run_id}-partial.json', partial)
                    print(scenario['id'], scenario['kind'], proposal['status'],
                          'PASS' if all(checks.values()) else 'FAIL', flush=True)

            await asyncio.gather(*(one(scenario) for scenario in document['llm_cases']
                                   if scenario['id'] not in completed))
            return sorted(records, key=lambda row: row['scenario_id'])

    records = asyncio.run(execute())
    traces = traces_for([run_id])
    metrics = {name: metric(records, key) for name, key in (
        ('requirement_parsing_accuracy', 'requirement_parsing_accuracy'),
        ('budget_check_accuracy', 'budget_check_accuracy'),
        ('supplier_filtering_accuracy', 'supplier_filtering_accuracy'),
        ('compliance_accuracy', 'compliance_accuracy'),
        ('recommendation_validity', 'recommendation_validity'))}
    metrics.update(trace_metrics(traces))
    llm_calls = [row for row in traces if str(row.get('action', '')).startswith('LLM_')]
    performance = {
        'request_end_to_end': latency_summary([row['latency_ms'] for row in records]),
        'requirement_parsing': latency_summary([row['latency_ms'] for row in traces if row.get('action') == 'LLM_EXTRACT']),
        'a2a_call': latency_summary([row['latency_ms'] for row in traces if row.get('action') == 'A2A_CALL']),
        'mcp_call': latency_summary([row['latency_ms'] for row in traces if row.get('action') == 'MCP_CALL']),
        'supplier_query': latency_summary([row['latency_ms'] for row in traces
                                           if row.get('action') == 'MCP_CALL' and row.get('tool_name') == 'search_supplier_quotes']),
    }
    report = {'result': 'PASS' if all(all(row['checks'].values()) for row in records) else 'FAIL',
              'run_id': run_id, 'completed_at': utcnow(), 'evaluation_mode': 'REAL_LLM_INTEGRATION',
              'model': get_settings().qwen_model, 'seed': SEED, 'scenario_count': len(records),
              'real_llm_case_count': len(records), 'real_llm_call_count': len(llm_calls),
              'llm_call_actions': dict(Counter(row['action'] for row in llm_calls)),
              'token_usage': {'available': False, 'reason': 'Current validated gateway does not retain provider usage metadata'},
              'categories': dict(Counter(row['kind'] for row in records)), 'metrics': metrics,
              'performance': performance,
              'failures': [row['scenario_id'] for row in records if not all(row['checks'].values())],
              'records': records}
    json_write(LLM_REPORT, report)
    with TRACE_REPORT.open('a', encoding='utf-8') as handle:
        for row in traces:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({'result': report['result'], 'scenario_count': len(records),
                      'llm_calls': len(llm_calls), 'metrics': metrics}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['build', 'offline', 'llm', 'all'])
    args = parser.parse_args()
    scenarios = build_scenarios()
    if args.action == 'build':
        print(json.dumps({'seed': SEED, 'offline': len(scenarios['offline_proposal_cases']),
                          'resilience': len(scenarios['resilience_cases']), 'llm': len(scenarios['llm_cases']),
                          'total_before_workflow': sum(len(scenarios[key]) for key in
                                                       ('offline_proposal_cases', 'resilience_cases', 'llm_cases'))},
                         ensure_ascii=False))
    else:
        results = []
        if args.action in ('offline', 'all'):
            results.append(run_offline(scenarios))
        if args.action in ('llm', 'all'):
            results.append(run_llm(scenarios))
        raise SystemExit(0 if all(result['result'] == 'PASS' for result in results) else 1)
