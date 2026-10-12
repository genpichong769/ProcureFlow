"""Phase3 business boundary: only the existing Procurement MCP can mutate facts."""
import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from agents.common import AgentFailure
from config import get_settings

TOOLS = frozenset({
    'create_purchase_request','get_purchase_request','submit_purchase_request','cancel_purchase_request',
    'create_purchase_order','get_purchase_order','update_purchase_order_status',
    'validate_requester','validate_approver','record_approval','release_request_budget','set_purchase_request_approval',
})


class WorkflowMCP:
    async def call(self,name,arguments):
        if name not in TOOLS:
            raise AgentFailure('FORBIDDEN_WORKFLOW_TOOL')
        settings=get_settings()
        try:
            async with streamablehttp_client(settings.mcp_url('procurement'),timeout=settings.mcp_timeout_seconds,
                sse_read_timeout=settings.mcp_timeout_seconds) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await asyncio.wait_for(session.initialize(),settings.mcp_timeout_seconds)
                    discovered={tool.name for tool in (await session.list_tools()).tools}
                    if name not in discovered:raise AgentFailure('WORKFLOW_MCP_TOOL_MISSING')
                    response=await asyncio.wait_for(session.call_tool(name,arguments),settings.mcp_timeout_seconds)
                    if response.isError:raise AgentFailure('WORKFLOW_MCP_TOOL_ERROR')
                    envelope=json.loads(response.content[0].text)
                    if not envelope.get('ok'):
                        code=envelope.get('error',{}).get('code')
                        raise AgentFailure('MYSQL_UNAVAILABLE' if code=='DATABASE' else 'WORKFLOW_BUSINESS_RULE')
                    return envelope['data']
        except AgentFailure:raise
        except BaseExceptionGroup as group:
            def find(exc):
                if isinstance(exc,AgentFailure):return exc
                for child in getattr(exc,'exceptions',()):
                    if found:=find(child):return found
            failure=find(group)
            raise failure or AgentFailure('WORKFLOW_MCP_UNAVAILABLE')
        except Exception:
            raise AgentFailure('WORKFLOW_MCP_UNAVAILABLE') from None
