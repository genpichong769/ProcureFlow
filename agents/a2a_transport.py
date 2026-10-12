"""Actual python-a2a network client; request/result payloads are JSON contracts."""
import asyncio
import json
from time import perf_counter
from uuid import uuid4
from agents.common import AgentFailure, trace, milliseconds
from config import get_settings

NAMES = dict(budget='BudgetAgent',supplier='SupplierSourcingAgent',compliance='ComplianceApprovalAgent',procurement='ProcurementCoordinatorAgent')


class A2ATransport:
    async def call(self,role,payload):
        from python_a2a import A2AClient,Message,TextContent,MessageRole,Task
        settings = get_settings()
        request_id = payload['request_id']
        for attempt in range(settings.agent_max_retries+1):
            start = perf_counter()
            try:
                async def send():
                    client = await asyncio.to_thread(A2AClient,settings.agent_url(role),timeout=settings.agent_timeout_seconds)
                    if client.agent_card.name!=NAMES[role]:
                        raise AgentFailure(role.upper()+'_AGENT_UNAVAILABLE')
                    message = Message(content=TextContent(text=json.dumps(payload,ensure_ascii=False)),role=MessageRole.USER)
                    response = await client.send_task_async(Task(id=uuid4().hex,message=message.to_dict()))
                    if not response.artifacts:
                        raise AgentFailure('A2A_INVALID_RESPONSE')
                    result = json.loads(response.artifacts[0]['parts'][0]['text'])
                    if not result.get('ok'):
                        raise AgentFailure(result.get('error_type','REMOTE_AGENT_ERROR'))
                    return result['data']
                data = await asyncio.wait_for(send(),settings.agent_timeout_seconds)
                trace(request_id,'ProcurementCoordinatorAgent','A2A_CALL',target_agent=NAMES[role],latency_ms=milliseconds(start))
                return data
            except AgentFailure as exc:
                trace(request_id,'ProcurementCoordinatorAgent','A2A_CALL',target_agent=NAMES[role],status='ERROR',latency_ms=milliseconds(start),error_type=exc.code)
                raise
            except Exception as exc:
                code = 'A2A_TIMEOUT' if isinstance(exc,TimeoutError) else role.upper()+'_AGENT_UNAVAILABLE'
                trace(request_id,'ProcurementCoordinatorAgent','A2A_CALL',target_agent=NAMES[role],status='ERROR',latency_ms=milliseconds(start),error_type=code)
                if attempt==settings.agent_max_retries:
                    raise AgentFailure(code) from None
