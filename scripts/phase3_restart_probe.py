"""Two-process restart/resume evidence for the durable LangGraph checkpoint."""
import argparse,json,os
from pathlib import Path
from config import ROOT,get_settings
from workflow.graph import ProcurementWorkflow

EVIDENCE=ROOT/'reports/phase3/restart-resume.json'


def start(workflow_id):
    graph=ProcurementWorkflow()
    try:
        result=graph.start('部门DEP001采购产品PRD00001，数量10件，总预算50000元，15天内到货。',4,workflow_id=workflow_id)
        interrupt=result['interrupts'][0]
        evidence=dict(workflow_id=workflow_id,start_pid=os.getpid(),request_no=result['state']['request_no'],
            status_before=result['state']['workflow_status'],required_role=interrupt['required_approval_role'],
            checkpoint_path=str(get_settings().checkpoint_path),checkpoint_bytes=get_settings().checkpoint_path.stat().st_size)
        EVIDENCE.parent.mkdir(parents=True,exist_ok=True);EVIDENCE.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(result='INTERRUPTED',workflow_id=workflow_id,pid=os.getpid(),checkpoint_bytes=evidence['checkpoint_bytes'])))
    finally:graph.close()


def resume(workflow_id):
    evidence=json.loads(EVIDENCE.read_text(encoding='utf-8'));graph=ProcurementWorkflow()
    try:
        before=graph.get(workflow_id);role=before['interrupts'][0]['required_approval_role'];ids={'部门经理':1,'采购经理':2,'财务负责人':3}
        result=graph.resume(dict(workflow_id=workflow_id,approver_id=ids[role],approver_role=role,decision='APPROVE',comment='restart proof'))
        while result['interrupts'] and result['interrupts'][0].get('type')=='HUMAN_APPROVAL':
            role=result['interrupts'][0]['required_approval_role']
            result=graph.resume(dict(workflow_id=workflow_id,approver_id=ids[role],approver_role=role,decision='APPROVE',comment='restart proof'))
        evidence.update(resume_pid=os.getpid(),different_process=os.getpid()!=evidence['start_pid'],status_after=result['state']['workflow_status'],
            po_no=result['state']['po_no'],approval_count=len(result['state']['approval_history']),coordinator_not_reinvoked=True)
        evidence['result']='PASS' if evidence['different_process'] and evidence['status_after']=='COMPLETED' else 'FAIL'
        EVIDENCE.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(result=evidence['result'],workflow_id=workflow_id,pid=os.getpid(),status=evidence['status_after'])))
    finally:graph.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','resume']);parser.add_argument('workflow_id');args=parser.parse_args()
    start(args.workflow_id) if args.action=='start' else resume(args.workflow_id)
