from .helpers import workflow


def test_three_levels_each_interrupt_and_record():
    chain=['部门经理','采购经理','财务负责人'];graph,mcp,path=workflow('multi',chain)
    graph.start('fixture',4,workflow_id='P3TEST-MULTI')
    for employee,role in zip((1,2,3),chain):
        result=graph.resume(dict(workflow_id='P3TEST-MULTI',approver_id=employee,approver_role=role,decision='APPROVE'))
    assert result['state']['workflow_status']=='COMPLETED'
    assert [x['approver_role'] for x in result['state']['approval_history']]==chain
    assert len(mcp.approvals)==3
    graph.close();path.unlink()
