from workflow.state import ProcurementWorkflowState
from workflow.approval import ApprovalDecision
import pytest
from pydantic import ValidationError


def test_typed_state_and_decision_contracts():
    assert 'workflow_id' in ProcurementWorkflowState.__annotations__
    value=ApprovalDecision(workflow_id='P3TEST-X',approver_id=1,approver_role='部门经理',decision='APPROVE')
    assert value.comment==''
    with pytest.raises(ValidationError):ApprovalDecision(workflow_id='X',approver_id=1,approver_role='部门经理',decision='EDIT')
