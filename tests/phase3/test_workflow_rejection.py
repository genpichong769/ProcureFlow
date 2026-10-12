import pytest
from agents.common import AgentFailure
from .helpers import workflow


@pytest.mark.parametrize('level',[0,1])
def test_rejection_releases_budget_and_never_creates_po(level):
    chain=['部门经理','采购经理'];graph,mcp,path=workflow('reject'+str(level),chain)
    graph.start('fixture',4,workflow_id='P3TEST-REJECT'+str(level))
    if level:graph.resume(dict(workflow_id='P3TEST-REJECT'+str(level),approver_id=1,approver_role='部门经理',decision='APPROVE'))
    role=chain[level];result=graph.resume(dict(workflow_id='P3TEST-REJECT'+str(level),approver_id=level+1,approver_role=role,decision='REJECT'))
    assert result['state']['workflow_status']=='REJECTED'
    names=[n for n,_ in mcp.calls];assert 'release_request_budget' in names and 'create_purchase_order' not in names
    with pytest.raises(AgentFailure,match='WORKFLOW_NOT_WAITING_APPROVAL'):
        graph.resume(dict(workflow_id='P3TEST-REJECT'+str(level),approver_id=1,approver_role='部门经理',decision='APPROVE'))
    graph.close();path.unlink()
