from .helpers import workflow


def test_single_level_approve_executes_and_verifies_po():
    graph,mcp,path=workflow('single')
    graph.start('fixture',4,workflow_id='P3TEST-SINGLE')
    result=graph.resume(dict(workflow_id='P3TEST-SINGLE',approver_id=1,approver_role='部门经理',decision='APPROVE',comment='ok'))
    state=result['state']
    assert state['workflow_status']=='COMPLETED' and state['purchase_order_status']=='CONFIRMED'
    assert [n for n,_ in mcp.calls].count('create_purchase_order')==1
    assert [n for n,_ in mcp.calls].count('get_purchase_order')==1
    graph.close();path.unlink()
