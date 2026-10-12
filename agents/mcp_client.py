"""Read-only capability boundary. No procurement write server or arbitrary tool execution."""
import asyncio
from contextlib import asynccontextmanager
import json
from time import perf_counter
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from agents.common import AgentFailure, trace, milliseconds
from config import get_settings

TOOLS = {
    'budget':('get_department_budget','check_budget'),
    'supplier':('search_supplier_quotes','get_supplier_detail','get_supplier_performance'),
    'compliance':('get_supplier_qualifications','get_procurement_rules','evaluate_procurement_compliance'),
}


class ReadOnlyMCP:
    def __init__(self, role, request_id, agent_name):
        if role not in TOOLS:
            raise AgentFailure('FORBIDDEN_MCP_SERVER')
        self.role,self.request_id,self.agent_name = role,request_id,agent_name

    @asynccontextmanager
    async def connect(self):
        settings = get_settings()
        try:
            async with streamablehttp_client(settings.mcp_url(self.role),timeout=settings.mcp_timeout_seconds,
                sse_read_timeout=settings.mcp_timeout_seconds) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await asyncio.wait_for(session.initialize(),settings.mcp_timeout_seconds)
                    discovered = {t.name for t in (await session.list_tools()).tools}
                    if not set(TOOLS[self.role])<=discovered:
                        raise AgentFailure('MCP_TOOL_MISSING')
                    self.session = session
                    yield self
        except BaseExceptionGroup as group:
            # Context managers can wrap business failures in task groups.
            def business(exc):
                if isinstance(exc,AgentFailure): return exc
                for child in getattr(exc,'exceptions',[]):
                    found = business(child)
                    if found: return found
            failure = business(group)
            code = failure.code if failure else 'MCP_UNAVAILABLE'
            trace(self.request_id,self.agent_name,'MCP_SESSION',target_agent=self.role,status='ERROR',error_type=code)
            raise AgentFailure(code) from None
        except AgentFailure:
            raise
        except Exception:
            trace(self.request_id,self.agent_name,'MCP_SESSION',target_agent=self.role,status='ERROR',error_type='MCP_UNAVAILABLE')
            raise AgentFailure('MCP_UNAVAILABLE') from None

    async def call(self, name, arguments):
        if name not in TOOLS[self.role]:
            raise AgentFailure('FORBIDDEN_TOOL')
        settings = get_settings()
        for attempt in range(settings.agent_max_retries+1):
            start = perf_counter()
            try:
                response = await asyncio.wait_for(self.session.call_tool(name,arguments),settings.mcp_timeout_seconds)
                if response.isError:
                    raise AgentFailure('MCP_TOOL_ERROR')
                envelope = json.loads(response.content[0].text)
                if not envelope.get('ok'):
                    code = envelope.get('error',{}).get('code')
                    raise AgentFailure('MYSQL_UNAVAILABLE' if code=='DATABASE' else 'TOOL_BUSINESS_RULE')
                trace(self.request_id,self.agent_name,'MCP_CALL',target_agent=self.role,tool_name=name,latency_ms=milliseconds(start))
                return envelope['data']
            except AgentFailure as exc:
                trace(self.request_id,self.agent_name,'MCP_CALL',target_agent=self.role,tool_name=name,status='ERROR',latency_ms=milliseconds(start),error_type=exc.code)
                raise
            except Exception:
                trace(self.request_id,self.agent_name,'MCP_CALL',target_agent=self.role,tool_name=name,status='ERROR',latency_ms=milliseconds(start),error_type='MCP_UNAVAILABLE')
                if attempt==settings.agent_max_retries:
                    raise AgentFailure('MCP_UNAVAILABLE') from None
