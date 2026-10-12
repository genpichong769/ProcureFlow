from fastapi.testclient import TestClient
import api.workflow_api as module
from .helpers import workflow


def test_minimal_api_start_query_approve_result():
    graph,_,path=workflow('api')
    module.workflow=graph
    client=TestClient(module.app)
    started=client.post('/api/workflows',json={'user_query':'fixture','requester_id':4}).json()
    wid=started['state']['workflow_id'];role=started['interrupts'][0]['required_approval_role']
    assert client.get('/api/workflows/'+wid).status_code==200
    completed=client.post('/api/workflows/'+wid+'/approve',json={'approver_id':1,'approver_role':role,'comment':'api'}).json()
    assert completed['state']['workflow_status']=='COMPLETED'
    assert client.get('/api/workflows/'+wid+'/result').status_code==200
    assert client.get('/api/workflows/P3TEST-MISSING').status_code==404
    graph.close();module.workflow=None;path.unlink()
