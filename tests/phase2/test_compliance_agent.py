import asyncio
import pytest
from agents.specialists import ComplianceApprovalAgent
from .helpers import FakeMCP,llm


@pytest.mark.parametrize('failure',[None,'BLACKLISTED','EXPIRED','REVOKED','MINIMUM_QUOTE_COUNT'])
def test_rule_failure_cannot_be_overridden(failure):
    failed=[] if failure is None else [dict(passed=False,rule_code=failure,reason='from deterministic rule')]
    mcp=FakeMCP(dict(get_supplier_qualifications=[],get_procurement_rules=[],evaluate_procurement_compliance=dict(
        compliance_passed=not failed,approval_chain=['部门经理','采购经理'],warnings=[],failed_rules=failed)))
    gateway=llm()
    results=asyncio.run(ComplianceApprovalAgent(gateway,mcp).run(dict(request_id='TEST',checks=[dict(
        request_id='TEST',department_code='DEP001',supplier_id=1,category='IT',total_amount='150000',valid_quote_count=2)])))
    assert results[0].compliance_passed is (failure is None)
    assert results[0].failed_rules==failed and results[0].required_quote_count==3
    gateway.explanation.assert_not_called()
    assert {n for n,_ in mcp.calls}=={'get_supplier_qualifications','get_procurement_rules','evaluate_procurement_compliance'}
