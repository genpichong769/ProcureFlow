import asyncio
import json
import logging
from time import perf_counter
from python_a2a import A2AServer,AgentCard,AgentSkill,TaskStatus,TaskState,run_server
from agents.common import AgentFailure, trace, milliseconds
from agents.a2a_transport import NAMES
from config import get_settings


class ProcurementA2AServer(A2AServer):
    def __init__(self,role,agent):
        self.role,self.agent = role,agent
        super().__init__(agent_card=AgentCard(name=NAMES[role],description='只读采购建议与专业校验，不审批不下单',
            url=get_settings().agent_url(role),version='2.0.0',capabilities={'streaming':False},
            skills=[AgentSkill(name=role+'_analysis',description='通过受控能力返回Pydantic结构化采购结果')]))

    def handle_task(self,task):
        request_id = 'INVALID'
        start = perf_counter()
        try:
            payload = json.loads((task.message or {}).get('content',{}).get('text',''))
            request_id = payload.get('request_id','INVALID')
            result = asyncio.run(self.agent.run(payload))
            data = [r.model_dump(mode='json') for r in result] if isinstance(result,list) else result.model_dump(mode='json')
            envelope = dict(ok=True,data=data)
            task.status = TaskStatus(state=TaskState.COMPLETED)
            trace(request_id,NAMES[self.role],'A2A_HANDLE',latency_ms=milliseconds(start))
        except Exception as exc:
            code = exc.code if isinstance(exc,AgentFailure) else 'INVALID_AGENT_INPUT'
            envelope = dict(ok=False,error_type=code)
            task.status = TaskStatus(state=TaskState.FAILED)
            trace(request_id,NAMES[self.role],'A2A_HANDLE',status='ERROR',latency_ms=milliseconds(start),error_type=code)
        task.artifacts = [{'parts':[{'type':'text','text':json.dumps(envelope,ensure_ascii=False)}]}]
        return task


def serve(role,agent):
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    run_server(ProcurementA2AServer(role,agent),host=get_settings().agent_host,
               port=getattr(get_settings(),'a2a_'+role+'_port'))
