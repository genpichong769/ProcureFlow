import asyncio
from decimal import Decimal
import pytest
from agents.specialists import BudgetAgent
from agents.common import AgentFailure
from .helpers import FakeMCP,llm


@pytest.mark.parametrize('amount,passed',[('2000',True),('9000',False)])
def test_real_tool_amount_is_authoritative(amount,passed):
    mcp=FakeMCP({'get_department_budget':dict(department_code='DEP001',total_budget='10000',used_budget='1000',reserved_budget='1000',available_budget='8000'),
        'check_budget':dict(passed=passed,reason='rule decision')})
    result=asyncio.run(BudgetAgent(llm(),mcp).run(dict(request_id='TEST',department_code='DEP001',requested_amount=amount)))
    assert result.budget_ok is passed and result.available_budget==Decimal(8000)
    assert result.remaining_after_purchase==Decimal(8000)-Decimal(amount)
    assert [n for n,_ in mcp.calls]==['get_department_budget','check_budget']


def test_nonexistent_department():
    mcp=FakeMCP({'get_department_budget':AgentFailure('TOOL_BUSINESS_RULE')})
    with pytest.raises(AgentFailure,match='TOOL_BUSINESS_RULE'):
        asyncio.run(BudgetAgent(llm(),mcp).run(dict(request_id='TEST',department_code='UNKNOWN',requested_amount='10')))


def test_llm_plan_drives_independent_tool_order():
    gateway=llm();gateway.select_tools.side_effect=None
    gateway.select_tools.return_value=['check_budget','get_department_budget']
    mcp=FakeMCP({'get_department_budget':dict(department_code='DEP001',total_budget='10000',used_budget='1000',reserved_budget='1000',available_budget='8000'),
        'check_budget':dict(passed=True,reason='rule decision')})
    asyncio.run(BudgetAgent(gateway,mcp).run(dict(request_id='TEST',department_code='DEP001',requested_amount='10')))
    assert [n for n,_ in mcp.calls]==['check_budget','get_department_budget']
