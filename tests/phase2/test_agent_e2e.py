import asyncio
from uuid import uuid4
from agents.a2a_transport import A2ATransport
from agents.schemas import ProcurementProposal


def test_real_qwen_coordinator_three_agents_mcp_mysql(real_stack):
    data=asyncio.run(A2ATransport().call('procurement',dict(request_id='INTEG-'+uuid4().hex,
        text='部门DEP001采购产品PRD00001，数量10件，总预算50000元，15天内到货。')))
    proposal=ProcurementProposal.model_validate(data)
    assert proposal.status=='READY_FOR_APPROVAL'
    assert proposal.budget_result.budget_ok and proposal.compliance_result.compliance_passed
    assert proposal.recommended_supplier==proposal.qualified_candidates[0]
    assert proposal.recommended_supplier.supplier_code.startswith('SUP')


def test_real_qwen_missing_fields(real_stack):
    data=asyncio.run(A2ATransport().call('procurement',dict(request_id='INTEG-'+uuid4().hex,
        text='帮部门DEP001买一些产品PRD00001，数量、预算、交期还没确定。')))
    assert data['status']=='NEED_MORE_INFORMATION'
    assert set(data['missing_fields'])=={'quantity','budget','delivery_deadline'}
    assert data['budget_result'] is None and data['recommended_supplier'] is None
