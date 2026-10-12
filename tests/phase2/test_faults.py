import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from config import get_settings
from agents.common import AgentFailure
from agents.mcp_client import ReadOnlyMCP
from agents.a2a_transport import A2ATransport
from agents.llm import QwenGateway


def test_write_capability_is_unreachable():
    with pytest.raises(AgentFailure,match='FORBIDDEN_MCP_SERVER'):ReadOnlyMCP('procurement','TEST','Test')
    with pytest.raises(AgentFailure,match='FORBIDDEN_TOOL'):
        asyncio.run(ReadOnlyMCP('budget','TEST','Test').call('create_purchase_order',{}))


def test_database_failure_is_sanitized():
    mcp=ReadOnlyMCP('budget','TEST','Test');mcp.session=SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
        isError=False,content=[SimpleNamespace(text=json.dumps(dict(ok=False,error=dict(code='DATABASE',message='private connection details'))))])))
    with pytest.raises(AgentFailure,match='^MYSQL_UNAVAILABLE$'):
        asyncio.run(mcp.call('get_department_budget',dict(department='DEP001')))
    assert mcp.session.call_tool.await_count==1


def test_mcp_unavailable_real_socket(monkeypatch):
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        settings=get_settings().model_copy(update=dict(mcp_budget_port=port,mcp_timeout_seconds=.2,agent_max_retries=0))
        monkeypatch.setattr('agents.mcp_client.get_settings',lambda:settings)
        async def run():
            async with ReadOnlyMCP('budget','FAULT-MCP','Test').connect():pass
        with pytest.raises(AgentFailure,match='MCP_UNAVAILABLE'):asyncio.run(run())


@pytest.mark.parametrize('role',['budget','supplier','compliance'])
def test_a2a_agent_unavailable_real_socket(monkeypatch,role):
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        settings=get_settings().model_copy(update={f'a2a_{role}_port':port,'agent_timeout_seconds':10,'agent_max_retries':0})
        monkeypatch.setattr('agents.a2a_transport.get_settings',lambda:settings)
        with pytest.raises(AgentFailure,match=role.upper()+'_AGENT_UNAVAILABLE'):
            asyncio.run(A2ATransport().call(role,dict(request_id='FAULT-A2A')))


def test_a2a_timeout_and_finite_retry(monkeypatch):
    calls=[]
    class SlowClient:
        def __init__(self,*a,**kw):self.agent_card=SimpleNamespace(name='BudgetAgent')
        async def send_task_async(self,*a):calls.append(1);await asyncio.sleep(1)
    monkeypatch.setattr('python_a2a.A2AClient',SlowClient)
    settings=get_settings().model_copy(update=dict(agent_timeout_seconds=.05,agent_max_retries=1))
    monkeypatch.setattr('agents.a2a_transport.get_settings',lambda:settings)
    with pytest.raises(AgentFailure,match='A2A_TIMEOUT'):asyncio.run(A2ATransport().call('budget',dict(request_id='FAULT-TIMEOUT')))
    assert len(calls)==2


def test_llm_invalid_schema_finite_retry(monkeypatch):
    settings=get_settings().model_copy(update=dict(agent_max_retries=1))
    monkeypatch.setattr('agents.llm.get_settings',lambda:settings)
    operation=AsyncMock(side_effect=ValueError('invalid structured output'))
    with pytest.raises(AgentFailure,match='LLM_STRUCTURED_OUTPUT_FAILURE'):
        asyncio.run(QwenGateway()._call(operation,'FAULT-LLM','Test','LLM_EXTRACT'))
    assert operation.await_count==2


def test_actual_mcp_with_unreachable_database(monkeypatch):
    import socket
    from urllib.parse import urlsplit
    from db.connection import Database
    from mcp_server.mcp_budget_server import create_server
    from tests.test_mcp_http import live_server
    with socket.socket() as closed:
        closed.bind(('127.0.0.1',0))
        settings=get_settings().model_copy(update=dict(db_port=closed.getsockname()[1],db_pool_size=1))
        mcp=create_server(Database(settings))
        with live_server(mcp.streamable_http_app()) as url:
            clientsettings=get_settings().model_copy(update=dict(mcp_budget_port=urlsplit(url).port))
            monkeypatch.setattr('agents.mcp_client.get_settings',lambda:clientsettings)
            async def run():
                async with ReadOnlyMCP('budget','FAULT-DB','Test').connect() as client:
                    await client.call('get_department_budget',dict(department='DEP001'))
            with pytest.raises(AgentFailure,match='MYSQL_UNAVAILABLE'):asyncio.run(run())
