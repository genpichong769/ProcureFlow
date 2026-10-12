import asyncio
from datetime import date,timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from agents.coordinator import ProcurementCoordinatorAgent,rank,prepare_requirement
from agents.schemas import ProcurementRequirement,RequirementFields
from agents.common import AgentFailure
from .helpers import llm,requirement,candidate,budget,compliance

FIXTURE_TEXT = 'DEP001采购PRD00001共10件，总预算2000元，7天内送达'


@pytest.mark.parametrize('expected',['READY_FOR_APPROVAL','NO_BUDGET','NO_SUPPLIER','COMPLIANCE_FAILED','ERROR'])
def test_coordinator_outcomes_and_real_boundaries(expected):
    transport=AsyncMock();gateway=llm()
    async def respond(role,payload):
        if expected=='ERROR':raise AgentFailure('BUDGET_AGENT_UNAVAILABLE')
        if role=='budget':return budget(expected!='NO_BUDGET')
        if role=='supplier':return dict(request_id='TEST',candidate_count=0 if expected=='NO_SUPPLIER' else 1,candidates=[] if expected=='NO_SUPPLIER' else [candidate().model_dump(mode='json')])
        return [compliance(expected!='COMPLIANCE_FAILED')]
    transport.call.side_effect=respond
    p=asyncio.run(ProcurementCoordinatorAgent(gateway,transport).run(dict(request_id='TEST',text=FIXTURE_TEXT)))
    assert p.status==expected
    if expected=='READY_FOR_APPROVAL':
        assert p.recommended_supplier.quote_id==1 and p.recommended_supplier.final_score==Decimal('99.350000')
        assert [call.args[0] for call in transport.call.call_args_list]==['budget','supplier','compliance']
        assert '1000.00' in p.recommendation_reason
    else:assert p.recommended_supplier is None


def test_missing_fields_never_guessed_or_dispatched():
    gateway=llm();gateway.extract.return_value=RequirementFields(department_code='DEP001',product_name='显示器')
    transport=AsyncMock()
    p=asyncio.run(ProcurementCoordinatorAgent(gateway,transport).run(dict(request_id='TEST',text='买一些显示器')))
    assert p.status=='NEED_MORE_INFORMATION' and set(p.missing_fields)=={'quantity','budget','delivery_deadline'}
    assert p.requirement.quantity is None and p.requirement.max_total_amount is None
    transport.call.assert_not_called()


def test_score_and_tie_break_are_deterministic():
    a=candidate(quote_id=2);b=candidate(quote_id=1)
    assert [c.quote_id for c in rank([a,b])]==[1,2]
    assert a.final_score is None


def test_budget_caps_and_absolute_deadline():
    r=ProcurementRequirement(request_id='TEST',**requirement(max_unit_price='90',required_delivery_date=date.today()+timedelta(days=4)))
    assert prepare_requirement(r)==[] and r.max_total_amount==Decimal(900) and r.max_delivery_days==4


@pytest.mark.parametrize('code',['A2A_TIMEOUT','BUDGET_AGENT_UNAVAILABLE','SUPPLIER_AGENT_UNAVAILABLE','COMPLIANCE_AGENT_UNAVAILABLE',
    'MCP_UNAVAILABLE','MYSQL_UNAVAILABLE','LLM_STRUCTURED_OUTPUT_FAILURE'])
def test_failures_produce_explicit_error(code):
    gateway=llm();transport=AsyncMock()
    if code=='LLM_STRUCTURED_OUTPUT_FAILURE':gateway.extract.side_effect=AgentFailure(code)
    stage='supplier' if code.startswith('SUPPLIER') else 'compliance' if code.startswith('COMPLIANCE') else 'budget'
    async def respond(role,payload):
        if role==stage:raise AgentFailure(code)
        if role=='budget':return budget()
        return dict(request_id='TEST',candidate_count=1,candidates=[candidate().model_dump(mode='json')])
    transport.call.side_effect=respond
    p=asyncio.run(ProcurementCoordinatorAgent(gateway,transport).run(dict(request_id='TEST',text=FIXTURE_TEXT)))
    assert p.status=='ERROR' and p.error_type==code and p.recommended_supplier is None
