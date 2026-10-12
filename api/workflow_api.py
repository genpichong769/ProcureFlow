"""Minimal FastAPI façade: start, inspect, resume, retry and read the result."""
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from agents.common import AgentFailure
from workflow.graph import ProcurementWorkflow
from workflow.approval import ApprovalDecision


class StartWorkflow(BaseModel):
    model_config=ConfigDict(extra='forbid')
    user_query: str=Field(min_length=1,max_length=4000)
    requester_id: int=Field(gt=0,strict=True)


class ApprovalBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    approver_id: int=Field(gt=0,strict=True)
    approver_role: str=Field(min_length=1,max_length=40)
    comment: str=Field(default='',max_length=1000)


workflow: ProcurementWorkflow | None=None


@asynccontextmanager
async def lifespan(app):
    global workflow
    workflow=ProcurementWorkflow()
    yield
    workflow.close();workflow=None


app=FastAPI(title='ProcureFlow Phase3 Workflow API',version='3.0.0',lifespan=lifespan)


def manager():
    if workflow is None:raise HTTPException(503,'Workflow runtime unavailable')
    return workflow


def safe(call):
    try:return call()
    except AgentFailure as exc:
        status=404 if exc.code=='WORKFLOW_NOT_FOUND' else 409
        raise HTTPException(status,exc.code) from None


@app.post('/api/workflows')
def start(body:StartWorkflow):
    return safe(lambda:manager().start(body.user_query,body.requester_id))


@app.get('/api/workflows/{workflow_id}')
def get_workflow(workflow_id:str):
    return safe(lambda:manager().get(workflow_id))


@app.post('/api/workflows/{workflow_id}/approve')
def approve(workflow_id:str,body:ApprovalBody):
    return safe(lambda:manager().resume(ApprovalDecision(workflow_id=workflow_id,decision='APPROVE',**body.model_dump())))


@app.post('/api/workflows/{workflow_id}/reject')
def reject(workflow_id:str,body:ApprovalBody):
    return safe(lambda:manager().resume(ApprovalDecision(workflow_id=workflow_id,decision='REJECT',**body.model_dump())))


@app.post('/api/workflows/{workflow_id}/retry')
def retry(workflow_id:str):
    return safe(lambda:manager().retry(workflow_id))


@app.get('/api/workflows/{workflow_id}/result')
def result(workflow_id:str):
    value=safe(lambda:manager().get(workflow_id))
    if value['state']['workflow_status'] not in ('COMPLETED','REJECTED','NEED_MORE_INFORMATION','ERROR'):
        raise HTTPException(409,'WORKFLOW_NOT_FINISHED')
    return value
