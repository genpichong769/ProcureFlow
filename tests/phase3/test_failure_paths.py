import pytest
from agents.common import AgentFailure
from .helpers import workflow,FakeMCP


class FailingMCP(FakeMCP):
    def __init__(self,tool,failures=1):super().__init__();self.tool=tool;self.failures=failures
    async def call(self,name,args):
        if name==self.tool and self.failures:
            self.failures-=1;self.calls.append((name,args));raise AgentFailure('TRANSIENT_TEST_FAILURE')
        return await super().call(name,args)


def test_reserve_failure_never_interrupts_for_approval():
    graph,mcp,path=workflow('reserve-failure',mcp=FailingMCP('submit_purchase_request'))
    result=graph.start('fixture',4,workflow_id='P3TEST-RESERVE-FAIL')
    assert result['state']['workflow_status']=='ERROR' and result['state']['last_error']=='TRANSIENT_TEST_FAILURE'
    assert result['interrupts']==[] and 'record_approval' not in [n for n,_ in mcp.calls]
    graph.close();path.unlink()


def test_approver_role_mismatch_is_rejected_before_database_record():
    graph,mcp,path=workflow('identity')
    graph.start('fixture',4,workflow_id='P3TEST-IDENTITY')
    with pytest.raises(AgentFailure,match='APPROVER_ROLE_MISMATCH'):
        graph.resume(dict(workflow_id='P3TEST-IDENTITY',approver_id=2,approver_role='采购经理',decision='APPROVE'))
    assert 'record_approval' not in [n for n,_ in mcp.calls]
    graph.close();path.unlink()


@pytest.mark.parametrize('tool',['create_purchase_order','update_purchase_order_status','get_purchase_order'])
def test_execution_failures_interrupt_then_recover_without_duplicate_po(tool):
    graph,mcp,path=workflow('recover-'+tool,mcp=FailingMCP(tool))
    graph.start('fixture',4,workflow_id='P3TEST-'+tool.upper())
    result=graph.resume(dict(workflow_id='P3TEST-'+tool.upper(),approver_id=1,approver_role='部门经理',decision='APPROVE'))
    assert result['interrupts'][0]['type']=='RECOVERY_REQUIRED' and result['interrupts'][0]['failed_node'] in ('execute_purchase','commit_budget','verify_purchase_order')
    result=graph.retry('P3TEST-'+tool.upper())
    assert result['state']['workflow_status']=='COMPLETED'
    assert mcp.order['id']==800001
    graph.close();path.unlink()


def test_unknown_and_completed_workflows_reject_invalid_actions():
    graph,_,path=workflow('notfound')
    with pytest.raises(AgentFailure,match='WORKFLOW_NOT_FOUND'):graph.get('P3TEST-MISSING')
    graph.start('fixture',4,workflow_id='P3TEST-DONE')
    graph.resume(dict(workflow_id='P3TEST-DONE',approver_id=1,approver_role='部门经理',decision='APPROVE'))
    with pytest.raises(AgentFailure,match='WORKFLOW_NOT_RECOVERABLE'):graph.retry('P3TEST-DONE')
    graph.close();path.unlink()
