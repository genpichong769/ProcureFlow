"""Thirty actual workflow scenarios over Qwen, A2A, MCP, LangGraph, SQLite and Docker MySQL."""
import argparse,asyncio,json,logging,sqlite3
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING
from pathlib import Path
from uuid import uuid4
from langgraph.checkpoint.sqlite import SqliteSaver
from agents.common import AgentFailure
from config import ROOT,get_settings
from db.connection import database
from db.repositories.base import all_rows,one
from scripts.evaluate_phase2 import Oracle
from workflow.graph import ProcurementWorkflow
from workflow.mcp_client import WorkflowMCP

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('mcp').setLevel(logging.WARNING)
SCENARIOS=get_settings().generated_dir/'phase3/workflow_scenarios.json'
REPORT=ROOT/'reports/phase3/evaluation.json'


def find_requirements(oracle,chain_length,count):
    found=[]
    for product_id in range(1,501):
        product=oracle.products.get(f'PRD{product_id:05}')
        if not product:continue
        quotes=[q for q in oracle.byproduct[product_id] if oracle.suppliers[q['supplier_id']]['status']=='ACTIVE' and oracle.valid_quals(q['supplier_id'])]
        if not quotes:continue
        minimum=min(q['unit_price'] for q in quotes)
        target=Decimal('8000') if chain_length==1 else Decimal('70000') if chain_length==2 else Decimal('220000')
        quantity=max(1,int((target/minimum).to_integral_value(rounding=ROUND_CEILING)))
        if quantity>1000000:continue
        requirement=dict(department_code=f'DEP{len(found)%5+1:03}',product_code=product['product_code'],quantity=quantity,
            max_total_amount=str((minimum*Decimal('1.60')*quantity).quantize(Decimal('.01'))),max_delivery_days=30)
        scenario=dict(kind='normal',requirement=requirement)
        expected=oracle.expected(scenario)
        if expected['status']!='READY_FOR_APPROVAL' or not expected['winner']:continue
        winner=oracle.byquote[expected['winner']];actual=winner['unit_price']*quantity
        comp=oracle.compliance(winner['supplier_id'],product['category'],actual,len({q['supplier_id'] for q in expected['candidates']}))
        if len(comp['approval_chain'])==chain_length:
            found.append(dict(requirement=requirement,approval_chain=comp['approval_chain']))
            if len(found)>=count:return found
    raise RuntimeError(f'Unable to build {count} real scenarios with approval chain length {chain_length}')


def build_scenarios():
    oracle=Oracle();single=find_requirements(oracle,1,10);multi=find_requirements(oracle,2,5)
    scenarios=[]
    def add(kind,source,reject_level=None,fault_tool=None):
        i=len(scenarios)+1;r=source['requirement']
        text=f"部门{r['department_code']}采购产品{r['product_code']}，数量{r['quantity']}件，总预算{r['max_total_amount']}元，{r['max_delivery_days']}天内到货。"
        scenarios.append(dict(id=f'W{i:02}',kind=kind,text=text,requirement=r,expected_chain=source['approval_chain'],
                              reject_level=reject_level,fault_tool=fault_tool))
    for row in single:add('single_approval',row)
    for row in multi:add('multi_approval',row)
    for i in range(5):add('rejection',multi[i%len(multi)],reject_level=i%2)
    for i in range(3):add('duplicate_resume',single[i])
    for i in range(3):add('checkpoint_recovery',single[i+3])
    add('budget_exception',single[6],fault_tool='submit_purchase_request')
    add('budget_exception',single[7],fault_tool='submit_purchase_request')
    add('po_recovery',single[8],fault_tool='create_purchase_order')
    add('po_recovery',single[9],fault_tool='update_purchase_order_status')
    assert len(scenarios)==30
    SCENARIOS.parent.mkdir(parents=True,exist_ok=True)
    if SCENARIOS.exists():
        existing=json.loads(SCENARIOS.read_text(encoding='utf-8'))
        if existing!=scenarios:raise RuntimeError('Fixed Phase3 scenario set changed')
    else:SCENARIOS.write_text(json.dumps(scenarios,ensure_ascii=False,indent=2),encoding='utf-8')
    return scenarios


class FailOnceMCP:
    def __init__(self,target):self.delegate=WorkflowMCP();self.target=target;self.failed=False
    async def call(self,name,args):
        if name==self.target and not self.failed:
            self.failed=True;raise AgentFailure('INJECTED_TRANSIENT_FAILURE')
        return await self.delegate.call(name,args)


def employees():
    with database.transaction() as conn:
        rows=all_rows(conn,"SELECT id,department_id,role FROM employees WHERE status='ACTIVE' AND role IN ('部门经理','采购经理','财务负责人','EMPLOYEE')")
    result={}
    for row in rows:result[(row['department_id'],row['role'])]=row['id']
    return result


def facts(request_id):
    with database.transaction() as conn:
        request=one(conn,'SELECT * FROM purchase_requests WHERE id=%s',(request_id,))
        approvals=all_rows(conn,'SELECT * FROM approval_records WHERE request_id=%s ORDER BY approval_level',(request_id,))
        tx=all_rows(conn,'SELECT * FROM budget_transactions WHERE request_id=%s ORDER BY id',(request_id,))
        orders=all_rows(conn,'SELECT * FROM purchase_orders WHERE request_id=%s',(request_id,))
        items=[]
        for order in orders:items.extend(all_rows(conn,'SELECT * FROM purchase_order_items WHERE purchase_order_id=%s',(order['id'],)))
    held=sum((r['amount'] if r['transaction_type']=='RESERVE' else -r['amount'] if r['transaction_type'] in ('RELEASE','COMMIT') else Decimal(0) for r in tx),Decimal(0))
    return dict(request=request,approvals=approvals,transactions=tx,orders=orders,order_items=items,held=str(held))


def reopen(graph,mcp):
    graph.close();path=get_settings().checkpoint_path
    connection=sqlite3.connect(path,check_same_thread=False);saver=SqliteSaver(connection);saver.setup()
    new=ProcurementWorkflow(connection=connection,checkpointer=saver);new.nodes.mcp=mcp
    return new


def evaluate():
    scenarios=build_scenarios();staff=employees();run_id='P3-'+uuid4().hex[:10];records=[]
    for scenario in scenarios:
        wid='P3TEST-'+run_id+'-'+scenario['id'];dept=int(scenario['requirement']['department_code'][3:]);requester=staff[(dept,'EMPLOYEE')]
        backend=FailOnceMCP(scenario['fault_tool']) if scenario['fault_tool'] else WorkflowMCP()
        graph=ProcurementWorkflow();graph.nodes.mcp=backend
        checks={};resume_attempts=0;valid_resumes=0;recovery_used=False;duplicate_rejected=False
        try:
            result=graph.start(scenario['text'],requester,workflow_id=wid)
            if scenario['kind']=='budget_exception':
                expected_status='ERROR'
            else:
                if scenario['kind']=='checkpoint_recovery':graph=reopen(graph,backend);result=graph.get(wid);recovery_used=True
                level=0
                while result['interrupts'] and result['interrupts'][0].get('type')=='HUMAN_APPROVAL':
                    role=result['interrupts'][0]['required_approval_role'];decision='REJECT' if scenario['kind']=='rejection' and level==scenario['reject_level'] else 'APPROVE'
                    resume_attempts+=1
                    result=graph.resume(dict(workflow_id=wid,approver_id=staff[(dept,role)],approver_role=role,decision=decision,comment='Phase3 E2E'))
                    valid_resumes+=1;level+=1
                    if decision=='REJECT':break
                if result['interrupts'] and result['interrupts'][0].get('type')=='RECOVERY_REQUIRED':
                    recovery_used=True;result=graph.retry(wid)
                expected_status='REJECTED' if scenario['kind']=='rejection' else 'COMPLETED'
                if scenario['kind']=='duplicate_resume' and result['state']['workflow_status']=='COMPLETED':
                    resume_attempts+=1
                    try:graph.resume(dict(workflow_id=wid,approver_id=staff[(dept,scenario['expected_chain'][0])],
                        approver_role=scenario['expected_chain'][0],decision='APPROVE'))
                    except AgentFailure as exc:duplicate_rejected=exc.code=='WORKFLOW_NOT_WAITING_APPROVAL'
            state=result['state'];db=facts(state['request_id'])
            history=state['approval_history'];expected_roles=scenario['expected_chain'][:len(history)]
            checks['workflow_completion']=state['workflow_status']==expected_status
            checks['approval_routing']=[h['approver_role'] for h in history]==expected_roles
            checks['resume_success']=valid_resumes==len(history)
            if expected_status=='COMPLETED':
                order=db['orders'][0] if len(db['orders'])==1 else None
                checks['purchase_order_integrity']=bool(order and order['id']==state['purchase_order_id'] and order['status']=='CONFIRMED'
                    and len(db['order_items'])==1 and Decimal(order['total_amount'])==Decimal(state['recommended_supplier']['total_price']))
            checks['budget_consistency']=Decimal(db['held'])==0 and (expected_status!='COMPLETED' or
                sum((t['amount'] for t in db['transactions'] if t['transaction_type']=='COMMIT'),Decimal(0))==Decimal(state['recommended_supplier']['total_price']))
            checks['duplicate_po']=len(db['orders'])<=1 and (scenario['kind']!='duplicate_resume' or duplicate_rejected)
            if scenario['kind'] in ('checkpoint_recovery','po_recovery'):checks['recovery_success']=recovery_used and expected_status=='COMPLETED' and state['workflow_status']=='COMPLETED'
            if scenario['kind']=='rejection':
                checks['human_rejection_correctness']=(state['workflow_status']=='REJECTED' and db['request']['status']=='REJECTED'
                    and any(a['decision']=='REJECTED' for a in db['approvals']) and not db['orders'] and Decimal(db['held'])==0)
            records.append(dict(id=scenario['id'],kind=scenario['kind'],workflow_id=wid,expected_status=expected_status,
                actual_status=state['workflow_status'],request_id=state['request_id'],request_no=state['request_no'],po_no=state.get('po_no'),
                approval_history=history,checks=checks,resume_attempts=resume_attempts,database=dict(request_status=db['request']['status'],
                    approval_count=len(db['approvals']),transaction_types=[t['transaction_type'] for t in db['transactions']],
                    order_count=len(db['orders']),held=db['held'])))
        except Exception as exc:
            records.append(dict(id=scenario['id'],kind=scenario['kind'],workflow_id=wid,actual_status='EXCEPTION',
                safe_error_type=type(exc).__name__,checks={'workflow_completion':False}))
        finally:graph.close()
        REPORT.parent.mkdir(parents=True,exist_ok=True)
        (REPORT.parent/(run_id+'-partial.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(scenario['id'],scenario['kind'],records[-1]['actual_status'],'PASS' if all(records[-1]['checks'].values()) else 'FAIL',flush=True)
    metrics={}
    mapping={'workflow_completion_rate':'workflow_completion','approval_routing_accuracy':'approval_routing','resume_success_rate':'resume_success',
        'purchase_order_integrity_rate':'purchase_order_integrity','budget_consistency_rate':'budget_consistency','recovery_success_rate':'recovery_success',
        'human_rejection_correctness':'human_rejection_correctness'}
    for metric,key in mapping.items():
        values=[r['checks'][key] for r in records if key in r['checks']];metrics[metric]=dict(numerator=sum(values),denominator=len(values),rate=sum(values)/len(values))
    eligible=[r for r in records if r.get('database',{}).get('order_count') is not None and r['expected_status']=='COMPLETED']
    duplicates=sum(r['database']['order_count']>1 for r in eligible)
    metrics['duplicate_po_rate']=dict(numerator=duplicates,denominator=len(eligible),rate=duplicates/len(eligible),formula='产生重复PO的完成型工作流 / 应创建PO的工作流')
    success=all(m['numerator']==m['denominator'] for k,m in metrics.items() if k!='duplicate_po_rate') and duplicates==0
    report=dict(result='PASS' if success else 'FAIL',run_id=run_id,completed_at=datetime.now(timezone.utc).isoformat(),
        scenario_file=str(SCENARIOS),scenario_count=len(records),categories=dict(Counter(s['kind'] for s in scenarios)),metrics=metrics,
        failures=[r['id'] for r in records if not all(r['checks'].values())],records=records)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(result=report['result'],metrics=metrics),ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--build-only',action='store_true');args=parser.parse_args()
    if args.build_only:
        value=build_scenarios();print(json.dumps(dict(count=len(value),categories=dict(Counter(x['kind'] for x in value))),ensure_ascii=False))
    else:raise SystemExit(0 if evaluate()['result']=='PASS' else 1)
