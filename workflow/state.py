"""Typed LangGraph state. MySQL remains authoritative for business facts."""
from typing import Any, Literal, TypedDict

WorkflowStatus = Literal['INITIALIZED','PROPOSAL_READY','PENDING_APPROVAL','REJECTED','APPROVED',
                         'EXECUTING','COMPLETED','ERROR','NEED_MORE_INFORMATION']


class ProcurementWorkflowState(TypedDict, total=False):
    workflow_id: str
    user_query: str
    requester_id: int
    requirement: dict[str,Any] | None
    proposal: dict[str,Any] | None
    budget_result: dict[str,Any] | None
    supplier_candidates: list[dict[str,Any]]
    qualified_candidates: list[dict[str,Any]]
    recommended_supplier: dict[str,Any] | None
    compliance_result: dict[str,Any] | None
    request_id: int | None
    request_no: str | None
    request_record: dict[str,Any] | None
    approval_chain: list[str]
    current_approval_index: int
    approval_history: list[dict[str,Any]]
    approval_status: str
    reserved_amount: str | None
    purchase_order_id: int | None
    po_no: str | None
    purchase_order_status: str | None
    purchase_order: dict[str,Any] | None
    workflow_status: WorkflowStatus
    proposal_status: str | None
    retry_count: int
    recovery_node: str | None
    last_error: str | None
    created_at: str
    updated_at: str
