"""Six new write-through Workflow cases for the Phase4 independent evaluation."""
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
from time import perf_counter
from uuid import uuid4

from agents.common import AgentFailure
from agents.coordinator import ProcurementCoordinatorAgent
from config import ROOT, get_settings
from scripts.evaluate_phase2 import Oracle
from scripts.evaluate_phase3 import FailOnceMCP, employees, facts, reopen
from scripts.phase3_stack import stack as phase3_stack
from scripts.phase3_test_data import capture, cleanup
from scripts.phase4_eval_support import DeterministicGateway
from scripts.phase4_offline_stack import stack as offline_stack
from workflow.graph import ProcurementWorkflow
from workflow.mcp_client import WorkflowMCP


REPORT = ROOT / 'reports' / 'phase4' / 'workflow-evaluation.json'
SOURCES = get_settings().require_persistent_path(get_settings().generated_dir / 'phase4' / 'workflow-sources.json')


class StaticProposalTransport:
    def __init__(self, proposal):
        self.proposal = proposal

    async def call(self, role, payload):
        if role != 'procurement':
            raise AgentFailure('UNEXPECTED_PHASE4_TRANSPORT_ROLE')
        value = deepcopy(self.proposal)
        value['request_id'] = payload['request_id']
        value['requirement']['request_id'] = payload['request_id']
        return value


def requirements(oracle, chain_length, count):
    found = []
    for product_id in range(1001, 4001):
        product = oracle.products[f'PRD{product_id:05}']
        rows = [row for row in oracle.byproduct[product_id]
                if oracle.suppliers[row['supplier_id']]['status'] == 'ACTIVE'
                and oracle.valid_quals(row['supplier_id'])]
        if not rows:
            continue
        minimum = min(row['unit_price'] for row in rows)
        target = Decimal('9000') if chain_length == 1 else Decimal('75000')
        quantity = max(1, int((target / minimum).to_integral_value(rounding=ROUND_CEILING)))
        requirement = {
            'department_code': f'DEP{11 + len(found):03}', 'product_code': product['product_code'],
            'quantity': quantity,
            'max_total_amount': str((minimum * Decimal('1.55') * quantity).quantize(Decimal('.01'))),
            'max_delivery_days': 45,
        }
        expected = oracle.expected({'kind': 'phase4_workflow', 'requirement': requirement})
        if expected['status'] != 'READY_FOR_APPROVAL' or not expected['winner']:
            continue
        winner = oracle.byquote[expected['winner']]
        actual = winner['unit_price'] * quantity
        compliance = oracle.compliance(winner['supplier_id'], product['category'], actual,
                                       len({row['supplier_id'] for row in expected['candidates']}))
        if len(compliance['approval_chain']) == chain_length:
            found.append(requirement)
            if len(found) == count:
                return found
    raise RuntimeError(f'Could not find {count} Phase4 workflow sources with chain {chain_length}')


def build_sources():
    oracle = Oracle()
    raw = requirements(oracle, 1, 3) + requirements(oracle, 2, 3)

    async def generate():
        coordinator = ProcurementCoordinatorAgent(llm=DeterministicGateway())
        output = []
        for index, requirement in enumerate(raw, 1):
            proposal = await coordinator.run({'request_id': f'P4WF-SOURCE-{index:02}', 'requirement': requirement})
            value = proposal.model_dump(mode='json')
            expected_length = 1 if index <= 3 else 2
            if value['status'] != 'READY_FOR_APPROVAL' or len(value['compliance_result']['approval_chain']) != expected_length:
                raise RuntimeError('Workflow source no longer satisfies its frozen prerequisite')
            output.append(value)
        return output

    with offline_stack():
        proposals = asyncio.run(generate())
    document = {'seed': 20261012, 'source_count': len(proposals), 'proposals': proposals}
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    if SOURCES.exists():
        current = json.loads(SOURCES.read_text(encoding='utf-8'))
        if current != document:
            raise RuntimeError('Frozen Phase4 workflow sources changed')
    else:
        SOURCES.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    return proposals


def evaluate():
    proposals = build_sources()
    definitions = [
        ('normal_single', proposals[0], None, None),
        ('rejection_second_level', proposals[3], 1, None),
        ('duplicate_resume', proposals[1], None, None),
        ('checkpoint_recovery', proposals[2], None, None),
        ('commit_recovery', proposals[4], None, 'update_purchase_order_status'),
        ('verification_recovery', proposals[5], None, 'get_purchase_order'),
    ]
    capture()
    run_id = 'P4WF-' + uuid4().hex[:10]
    staff = employees()
    records = []
    try:
        with phase3_stack():
            for index, (kind, proposal, reject_level, fault_tool) in enumerate(definitions, 1):
                workflow_id = f'P3TEST-{run_id}-W{index:02}'
                department_id = int(proposal['requirement']['department_code'][3:])
                requester = staff[(department_id, 'EMPLOYEE')]
                backend = FailOnceMCP(fault_tool) if fault_tool else WorkflowMCP()
                graph = ProcurementWorkflow()
                graph.nodes.transport = StaticProposalTransport(proposal)
                graph.nodes.mcp = backend
                start = perf_counter()
                valid_resumes = 0
                duplicate_rejected = False
                reopened = False
                recovery_used = False
                try:
                    result = graph.start('Phase4 deterministic workflow source', requester, workflow_id=workflow_id)
                    if kind == 'checkpoint_recovery':
                        graph = reopen(graph, backend)
                        graph.nodes.transport = StaticProposalTransport(proposal)
                        result = graph.get(workflow_id)
                        reopened = True
                    level = 0
                    while result['interrupts'] and result['interrupts'][0].get('type') == 'HUMAN_APPROVAL':
                        role = result['interrupts'][0]['required_approval_role']
                        decision = 'REJECT' if reject_level == level else 'APPROVE'
                        result = graph.resume({'workflow_id': workflow_id, 'approver_id': staff[(department_id, role)],
                                               'approver_role': role, 'decision': decision,
                                               'comment': 'Phase4 independent workflow evaluation'})
                        valid_resumes += 1
                        level += 1
                        if decision == 'REJECT':
                            break
                    while result['interrupts'] and result['interrupts'][0].get('type') == 'RECOVERY_REQUIRED':
                        recovery_used = True
                        result = graph.retry(workflow_id)
                    expected_status = 'REJECTED' if reject_level is not None else 'COMPLETED'
                    if kind == 'duplicate_resume' and result['state']['workflow_status'] == 'COMPLETED':
                        try:
                            role = proposal['compliance_result']['approval_chain'][0]
                            graph.resume({'workflow_id': workflow_id, 'approver_id': staff[(department_id, role)],
                                          'approver_role': role, 'decision': 'APPROVE', 'comment': 'duplicate'})
                        except AgentFailure as exc:
                            duplicate_rejected = exc.code == 'WORKFLOW_NOT_WAITING_APPROVAL'
                    state = result['state']
                    business = facts(state['request_id'])
                    order = business['orders'][0] if len(business['orders']) == 1 else None
                    expected_chain = proposal['compliance_result']['approval_chain']
                    checks = {
                        'workflow_completion': state['workflow_status'] == expected_status,
                        'approval_routing': [row['approver_role'] for row in state['approval_history']]
                            == expected_chain[:len(state['approval_history'])],
                        'resume_success': valid_resumes == len(state['approval_history']),
                        'budget_consistency': Decimal(business['held']) == 0,
                        'duplicate_po': len(business['orders']) <= 1,
                    }
                    if expected_status == 'COMPLETED':
                        checks['purchase_order_integrity'] = bool(
                            order and order['id'] == state['purchase_order_id'] and order['status'] == 'CONFIRMED'
                            and len(business['order_items']) == 1
                            and Decimal(order['total_amount']) == Decimal(state['recommended_supplier']['total_price'])
                            and sum((row['amount'] for row in business['transactions']
                                     if row['transaction_type'] == 'COMMIT'), Decimal(0))
                            == Decimal(order['total_amount']))
                    if kind == 'duplicate_resume':
                        checks['duplicate_resume_rejected'] = duplicate_rejected
                    if kind == 'checkpoint_recovery':
                        checks['checkpoint_resume'] = reopened and state['workflow_status'] == 'COMPLETED'
                    if fault_tool:
                        checks['recovery_success'] = recovery_used and state['workflow_status'] == 'COMPLETED'
                    if expected_status == 'REJECTED':
                        checks['rejection_consistency'] = (
                            business['request']['status'] == 'REJECTED' and not business['orders']
                            and any(row['decision'] == 'REJECTED' for row in business['approvals']))
                    row = {
                        'id': f'P4-W{index:02}', 'kind': kind, 'workflow_id': workflow_id,
                        'expected_status': expected_status, 'actual_status': state['workflow_status'],
                        'request_id': state['request_id'], 'po_no': state.get('po_no'),
                        'approval_chain': expected_chain, 'approval_history': state['approval_history'],
                        'latency_ms': round((perf_counter() - start) * 1000, 3), 'checks': checks,
                        'database': {'request_status': business['request']['status'],
                                     'approval_count': len(business['approvals']),
                                     'transaction_types': [item['transaction_type'] for item in business['transactions']],
                                     'order_count': len(business['orders']), 'held': business['held']},
                    }
                except Exception as exc:
                    row = {'id': f'P4-W{index:02}', 'kind': kind, 'workflow_id': workflow_id,
                           'actual_status': 'EXCEPTION', 'safe_error_type': type(exc).__name__,
                           'latency_ms': round((perf_counter() - start) * 1000, 3),
                           'checks': {'workflow_completion': False}}
                finally:
                    graph.close()
                records.append(row)
                REPORT.parent.mkdir(parents=True, exist_ok=True)
                (REPORT.parent / f'{run_id}-partial.json').write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
                print(row['id'], kind, row['actual_status'], 'PASS' if all(row['checks'].values()) else 'FAIL', flush=True)
    finally:
        cleanup()

    def metric(key):
        values = [row['checks'][key] for row in records if key in row['checks']]
        return {'numerator': sum(values), 'denominator': len(values),
                'rate': sum(values) / len(values) if values else None}

    metrics = {
        'workflow_completion_rate': metric('workflow_completion'),
        'approval_routing_accuracy': metric('approval_routing'),
        'checkpoint_resume_success_rate': metric('checkpoint_resume'),
        'purchase_order_integrity_rate': metric('purchase_order_integrity'),
        'budget_consistency_rate': metric('budget_consistency'),
    }
    eligible = [row for row in records if row.get('expected_status') == 'COMPLETED']
    duplicate_count = sum(row.get('database', {}).get('order_count', 0) > 1 for row in eligible)
    metrics['duplicate_purchase_order_rate'] = {
        'numerator': duplicate_count, 'denominator': len(eligible),
        'rate': duplicate_count / len(eligible) if eligible else None,
    }
    latencies = sorted(row['latency_ms'] for row in records)
    report = {
        'result': 'PASS' if all(all(row['checks'].values()) for row in records) else 'FAIL',
        'run_id': run_id, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'evaluation_mode': 'DETERMINISTIC_WORKFLOW_WITH_REAL_MCP_MYSQL',
        'scenario_count': len(records), 'categories': dict(Counter(row['kind'] for row in records)),
        'metrics': metrics,
        'performance': {'samples': len(latencies), 'p50_ms': latencies[(len(latencies)-1)//2],
                        'p95_ms': latencies[-1]},
        'failures': [row['id'] for row in records if not all(row['checks'].values())],
        'records': records,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': report['result'], 'metrics': metrics}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    raise SystemExit(0 if evaluate()['result'] == 'PASS' else 1)
