"""One Qwen client factory; no graph runtime and no unconstrained agent execution loop."""
import asyncio
import os
from functools import lru_cache
from time import perf_counter
from langchain_openai import ChatOpenAI
from agents.common import AgentFailure, trace, milliseconds
from agents.schemas import RequirementFields, ExplanationPlan
from agents.prompts import EXTRACTION, TOOL_SELECTION, EXPLANATION
from config import get_settings


@lru_cache
def client():
    key = os.getenv('DASHSCOPE_API_KEY')
    if not key:
        raise AgentFailure('LLM_KEY_UNAVAILABLE')
    settings = get_settings()
    return ChatOpenAI(api_key=key,base_url=settings.qwen_base_url,model=settings.qwen_model,
                      temperature=0,timeout=settings.llm_timeout_seconds,max_retries=0)


class QwenGateway:
    async def _call(self, operation, request_id, agent, action):
        settings = get_settings()
        for attempt in range(settings.agent_max_retries+1):
            start = perf_counter()
            try:
                value = await asyncio.wait_for(operation(),settings.llm_timeout_seconds)
                if value is None:
                    raise ValueError('empty structured output')
                trace(request_id,agent,action,status='SUCCESS',latency_ms=milliseconds(start))
                return value
            except Exception:
                trace(request_id,agent,action,status='ERROR',latency_ms=milliseconds(start),error_type='LLM_STRUCTURED_OUTPUT_FAILURE')
                if attempt==settings.agent_max_retries:
                    raise AgentFailure('LLM_STRUCTURED_OUTPUT_FAILURE') from None

    async def extract(self, text, request_id):
        chain = client().with_structured_output(RequirementFields,method='function_calling')
        return await self._call(lambda:asyncio.to_thread(chain.invoke,[('system',EXTRACTION),('human',text)]),
                                request_id,'ProcurementCoordinatorAgent','LLM_EXTRACT')

    async def select_tools(self, names, request_id, agent):
        specs = [{'type':'function','function':{'name':name,'description':'读取该专业任务所需真实数据：'+name,
                   'parameters':{'type':'object','properties':{},'additionalProperties':False}}} for name in names]
        async def choose():
            response = await asyncio.to_thread(client().bind_tools(specs,tool_choice='required').invoke,[
                ('system',TOOL_SELECTION),('human','完成本专业校验，需要这些证据：'+','.join(names))])
            selected = [c['name'] for c in response.tool_calls]
            if not selected or any(n not in names for n in selected):
                raise ValueError('invalid tool plan')
            # Mandatory evidence cannot be omitted by an LLM. Calls use validated program arguments.
            return list(dict.fromkeys(selected+list(names)))
        return await self._call(choose,request_id,agent,'LLM_TOOL_SELECTION')

    async def explanation(self, candidate, request_id):
        chain = client().with_structured_output(ExplanationPlan,method='function_calling')
        return await self._call(lambda:asyncio.to_thread(chain.invoke,[('system',EXPLANATION),('human',candidate.model_dump_json())]),
                                request_id,'ProcurementCoordinatorAgent','LLM_EXPLAIN')
