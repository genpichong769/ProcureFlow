from uuid import uuid4
from db.connection import database
from db.repositories.base import one,all_rows
from scripts.phase3_test_data import cleanup
from workflow.graph import ProcurementWorkflow


def test_real_qwen_a2a_mcp_interrupt_mysql_po_and_cleanup(real_phase3_stack):
    workflow_id='P3TEST-PYTEST-'+uuid4().hex[:10];graph=ProcurementWorkflow()
    try:
        result=graph.start('部门DEP001采购产品PRD00001，数量10件，总预算50000元，15天内到货。',4,workflow_id=workflow_id)
        ids={'部门经理':1,'采购经理':2,'财务负责人':3}
        assert result['interrupts'][0]['type']=='HUMAN_APPROVAL'
        while result['interrupts']:
            role=result['interrupts'][0]['required_approval_role']
            result=graph.resume(dict(workflow_id=workflow_id,approver_id=ids[role],approver_role=role,decision='APPROVE',comment='real pytest'))
        state=result['state'];assert state['workflow_status']=='COMPLETED'
        with database.transaction() as conn:
            request=one(conn,'SELECT * FROM purchase_requests WHERE id=%s',(state['request_id'],))
            order=one(conn,'SELECT * FROM purchase_orders WHERE request_id=%s',(state['request_id'],))
            approvals=all_rows(conn,'SELECT * FROM approval_records WHERE request_id=%s',(state['request_id'],))
            transactions=all_rows(conn,'SELECT * FROM budget_transactions WHERE request_id=%s',(state['request_id'],))
        assert request['request_no'].startswith('P3TEST-') and order['status']=='CONFIRMED'
        assert approvals and {t['transaction_type'] for t in transactions}=={'RESERVE','RELEASE','COMMIT'}
    finally:
        graph.close();cleanup()
