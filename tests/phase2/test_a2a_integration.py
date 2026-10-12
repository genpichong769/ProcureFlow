import asyncio
from uuid import uuid4
from decimal import Decimal
import pytest
from agents.a2a_transport import A2ATransport,NAMES
from agents.common import AgentFailure
from config import get_settings
from python_a2a import A2AClient


@pytest.mark.parametrize('role',list(NAMES))
def test_actual_agent_cards(real_stack,role):
    client=A2AClient(get_settings().agent_url(role))
    assert client.agent_card.name==NAMES[role]


def test_actual_budget_a2a_mcp_mysql_qwen(real_stack):
    result=asyncio.run(A2ATransport().call('budget',dict(request_id='INTEG-'+uuid4().hex,department_code='DEP001',requested_amount='2000')))
    assert result['budget_ok'] is True
    assert Decimal(result['available_budget'])==Decimal(result['total_budget'])-Decimal(result['used_budget'])-Decimal(result['reserved_budget'])


def test_actual_nonexistent_department_is_business_error(real_stack):
    with pytest.raises(AgentFailure,match='TOOL_BUSINESS_RULE'):
        asyncio.run(A2ATransport().call('budget',dict(request_id='INTEG-'+uuid4().hex,department_code='UNKNOWN-NONEXISTENT',requested_amount='10')))
