import pytest
from agents.common import AgentFailure
from .helpers import workflow


def test_completed_resume_and_duplicate_po_are_safe():
    graph,mcp,path=workflow('idempotency')
    graph.start('fixture',4,workflow_id='P3TEST-IDEMPOTENT')
    graph.resume(dict(workflow_id='P3TEST-IDEMPOTENT',approver_id=1,approver_role='部门经理',decision='APPROVE'))
    with pytest.raises(AgentFailure,match='WORKFLOW_NOT_WAITING_APPROVAL'):
        graph.resume(dict(workflow_id='P3TEST-IDEMPOTENT',approver_id=1,approver_role='部门经理',decision='APPROVE'))
    first=mcp.order
    import asyncio
    again=asyncio.run(mcp.call('create_purchase_order',dict(request_id=mcp.request_id)))
    assert again['id']==first['id']
    graph.close();path.unlink()
