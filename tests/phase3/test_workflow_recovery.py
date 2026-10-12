import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from workflow.graph import ProcurementWorkflow
from .helpers import workflow,FakeTransport,proposal


def test_restart_new_process_object_resumes_same_checkpoint():
    first,mcp,path=workflow('restart')
    first.start('fixture',4,workflow_id='P3TEST-RESTART');first.close()
    connection=sqlite3.connect(path,check_same_thread=False);saver=SqliteSaver(connection);saver.setup()
    second=ProcurementWorkflow(connection=connection,checkpointer=saver)
    second.nodes.transport=FakeTransport(proposal());second.nodes.mcp=mcp
    before=second.get('P3TEST-RESTART')
    assert before['interrupts'][0]['type']=='HUMAN_APPROVAL'
    result=second.resume(dict(workflow_id='P3TEST-RESTART',approver_id=1,approver_role='部门经理',decision='APPROVE'))
    assert result['state']['workflow_status']=='COMPLETED'
    assert len(second.nodes.transport.calls)==0
    second.close();path.unlink()
