from .helpers import workflow


def test_real_langgraph_interrupt_payload():
    graph,_,path=workflow('interrupt')
    result=graph.start('fixture query',4,workflow_id='P3TEST-INTERRUPT')
    assert result['state']['workflow_status']=='PENDING_APPROVAL'
    assert result['interrupts'][0]['type']=='HUMAN_APPROVAL'
    assert result['interrupts'][0]['required_approval_role']=='部门经理'
    assert path.exists() and path.stat().st_size>0
    graph.close();path.unlink()
