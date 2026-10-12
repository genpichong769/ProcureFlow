"""LangGraph nodes. Side effects cross only the A2A or Procurement MCP boundaries."""
import asyncio
from datetime import date,datetime,timezone,timedelta
from decimal import Decimal,ROUND_DOWN
from time import perf_counter
from langgraph.types import interrupt
from agents.a2a_transport import A2ATransport
from agents.common import AgentFailure
from agents.schemas import ProcurementProposal
from workflow.approval import ApprovalDecision,RecoveryDecision
from workflow.mcp_client import WorkflowMCP
from workflow.trace import workflow_trace,elapsed


def now():return datetime.now(timezone.utc).isoformat()


def run(awaitable):return asyncio.run(awaitable)


class WorkflowNodes:
    def __init__(self,transport=None,mcp=None):
        self.transport=transport or A2ATransport()
        self.mcp=mcp or WorkflowMCP()

    def event(self,state,node,event='SUCCESS',start=None,**extra):
        workflow_trace(state['workflow_id'],node,event,request_id=state.get('request_id'),
            duration_ms=elapsed(start) if start else 0,**extra)

    def build_proposal(self,state):
        start=perf_counter()
        data=run(self.transport.call('procurement',dict(request_id=state['workflow_id'],text=state['user_query'])))
        proposal=ProcurementProposal.model_validate(data).model_dump(mode='json')
        status=proposal['status']
        workflow_status='PROPOSAL_READY' if status=='READY_FOR_APPROVAL' else 'NEED_MORE_INFORMATION' if status=='NEED_MORE_INFORMATION' else 'ERROR'
        self.event(state,'build_proposal',start=start)
        return dict(proposal=proposal,proposal_status=status,requirement=proposal['requirement'],budget_result=proposal['budget_result'],
            supplier_candidates=proposal['all_candidates'],qualified_candidates=proposal['qualified_candidates'],
            recommended_supplier=proposal['recommended_supplier'],compliance_result=proposal['compliance_result'],
            workflow_status=workflow_status,last_error=None if status in ('READY_FOR_APPROVAL','NEED_MORE_INFORMATION') else status,updated_at=now())

    def create_purchase_request(self,state):
        start=perf_counter();req=state['requirement'];supplier=state['recommended_supplier']
        requester=run(self.mcp.call('validate_requester',dict(requester_id=state['requester_id'],department=req['department_code'])))
        quantity=req['quantity'];cap=Decimal(req['max_total_amount'])/quantity
        if req.get('max_unit_price') is not None:cap=min(cap,Decimal(req['max_unit_price']))
        cap=cap.quantize(Decimal('.01'),rounding=ROUND_DOWN)
        required=req.get('required_delivery_date') or (date.today()+timedelta(days=req['max_delivery_days'])).isoformat()
        prefix='P3TEST-' if state['workflow_id'].startswith('P3TEST-') else 'P3-'
        request_no=prefix+state['workflow_id'].removeprefix('P3TEST-').removeprefix('WF-')
        args=dict(requester_id=state['requester_id'],department_id=requester['department_id'],required_delivery_date=required,
            reason=(req.get('reason') or 'LangGraph采购方案')[:1000],request_no=request_no,
            items=[dict(product_id=supplier['product_id'],quantity=quantity,max_unit_price=str(cap))])
        record=run(self.mcp.call('create_purchase_request',args))
        self.event(state,'create_purchase_request',start=start)
        return dict(request_id=record['id'],request_no=record['request_no'],request_record=record,updated_at=now())

    def reserve_budget(self,state):
        start=perf_counter()
        try:
            record=run(self.mcp.call('submit_purchase_request',dict(request_id=state['request_id'])))
            self.event(state,'reserve_budget',start=start)
            return dict(request_record=record,reserved_amount=str(record['expected_budget']),workflow_status='PENDING_APPROVAL',updated_at=now())
        except AgentFailure as exc:
            self.event(state,'reserve_budget','ERROR',start,error_type=exc.code)
            return dict(workflow_status='ERROR',last_error=exc.code,updated_at=now())

    def prepare_approval(self,state):
        chain=state['compliance_result']['approval_chain']
        self.event(state,'prepare_approval')
        return dict(approval_chain=chain,current_approval_index=0,approval_history=[],
                    approval_status='PENDING' if chain else 'APPROVED',updated_at=now())

    def approval_payload(self,state):
        req=state['requirement'];supplier=state['recommended_supplier'];role=state['approval_chain'][state['current_approval_index']]
        return dict(type='HUMAN_APPROVAL',workflow_id=state['workflow_id'],request_no=state['request_no'],
            department=req['department_code'],product=req.get('product_code') or req.get('product_name'),quantity=req['quantity'],
            recommended_supplier=dict(id=supplier['supplier_id'],code=supplier['supplier_code'],name=supplier['supplier_name']),
            total_amount=supplier['total_price'],delivery_days=supplier['delivery_days'],on_time_rate=supplier['on_time_rate'],
            quality_rate=supplier['quality_rate'],budget_status=state['budget_result'],compliance_result=state['compliance_result'],
            required_approval_role=role,approval_level=state['current_approval_index']+1,approval_chain=state['approval_chain'],
            recommendation_reason=state['proposal']['recommendation_reason'])

    def human_approval(self,state):
        index=state['current_approval_index'];role=state['approval_chain'][index]
        self.event(state,'human_approval','INTERRUPT',checkpoint_status='PERSISTED',approval_level=index+1)
        decision=ApprovalDecision.model_validate(interrupt(self.approval_payload(state)))
        if decision.workflow_id!=state['workflow_id']:raise AgentFailure('WORKFLOW_ID_MISMATCH')
        if decision.approver_role!=role:raise AgentFailure('APPROVER_ROLE_MISMATCH')
        run(self.mcp.call('validate_approver',dict(request_id=state['request_id'],approver_id=decision.approver_id,required_role=role)))
        record=run(self.mcp.call('record_approval',dict(request_id=state['request_id'],approver_id=decision.approver_id,
            required_role=role,approval_level=index+1,decision=decision.decision,comment=decision.comment)))
        history=list(state['approval_history'])+[dict(approval_level=index+1,approver_id=decision.approver_id,
            approver_role=role,decision=decision.decision,comment=decision.comment,decided_at=record['decided_at'])]
        self.event(state,'human_approval','RESUME',approval_level=index+1,decision=decision.decision)
        return dict(approval_history=history,approval_status='REJECTED' if decision.decision=='REJECT' else 'APPROVED',
                    current_approval_index=index+(1 if decision.decision=='APPROVE' else 0),updated_at=now())

    def check_more_approvals(self,state):
        self.event(state,'check_more_approvals')
        return dict(updated_at=now())

    def next_approval(self,state):
        self.event(state,'next_approval',approval_level=state['current_approval_index']+1)
        return dict(approval_status='PENDING',updated_at=now())

    def release_budget(self,state):
        start=perf_counter();result=run(self.mcp.call('release_request_budget',dict(request_id=state['request_id'])))
        self.event(state,'release_budget',start=start)
        return dict(reserved_amount='0',request_record=result,updated_at=now())

    def mark_request_rejected(self,state):
        start=perf_counter();record=run(self.mcp.call('set_purchase_request_approval',dict(request_id=state['request_id'],status='REJECTED')))
        self.event(state,'mark_request_rejected',start=start)
        return dict(request_record=record,workflow_status='REJECTED',updated_at=now())

    def mark_request_approved(self,state):
        start=perf_counter();record=run(self.mcp.call('set_purchase_request_approval',dict(request_id=state['request_id'],status='APPROVED')))
        self.event(state,'mark_request_approved',start=start)
        return dict(request_record=record,workflow_status='APPROVED',approval_status='APPROVED',updated_at=now())

    def execute_purchase(self,state):
        start=perf_counter();supplier=state['recommended_supplier'];req=state['requirement']
        try:
            order=run(self.mcp.call('create_purchase_order',dict(request_id=state['request_id'],supplier_id=supplier['supplier_id'],
                items=[dict(product_id=supplier['product_id'],quote_id=supplier['quote_id'],quantity=req['quantity'])])))
            self.event(state,'execute_purchase',start=start,po_no=order['po_no'])
            return dict(purchase_order_id=order['id'],po_no=order['po_no'],purchase_order_status=order['status'],
                        purchase_order=order,workflow_status='EXECUTING',last_error=None,recovery_node=None,updated_at=now())
        except AgentFailure as exc:
            self.event(state,'execute_purchase','ERROR',start,error_type=exc.code)
            return dict(workflow_status='ERROR',last_error=exc.code,recovery_node='execute_purchase',updated_at=now())

    def commit_budget(self,state):
        start=perf_counter()
        try:
            order=run(self.mcp.call('update_purchase_order_status',dict(purchase_order_id=state['purchase_order_id'],status='CONFIRMED')))
            self.event(state,'commit_budget',start=start,po_no=order['po_no'])
            return dict(purchase_order=order,purchase_order_status=order['status'],reserved_amount='0',last_error=None,recovery_node=None,updated_at=now())
        except AgentFailure as exc:
            self.event(state,'commit_budget','ERROR',start,error_type=exc.code,po_no=state.get('po_no'))
            return dict(workflow_status='ERROR',last_error=exc.code,recovery_node='commit_budget',updated_at=now())

    def verify_purchase_order(self,state):
        start=perf_counter()
        try:
            order=run(self.mcp.call('get_purchase_order',dict(purchase_order_id=state['purchase_order_id'])))
            req=state['requirement'];supplier=state['recommended_supplier'];items=order['items']
            valid=(order['request_id']==state['request_id'] and order['supplier_id']==supplier['supplier_id']
                and order['department_id']==state['request_record']['department_id'] and order['status']=='CONFIRMED'
                and len(items)==1 and items[0]['product_id']==supplier['product_id'] and items[0]['quote_id']==supplier['quote_id']
                and items[0]['quantity']==req['quantity'] and Decimal(items[0]['unit_price'])==Decimal(supplier['unit_price'])
                and Decimal(items[0]['total_price'])==Decimal(supplier['total_price'])
                and Decimal(order['total_amount'])==Decimal(supplier['total_price']))
            if not valid:raise AgentFailure('PO_INTEGRITY_FAILURE')
            self.event(state,'verify_purchase_order',start=start,po_no=order['po_no'])
            return dict(purchase_order=order,purchase_order_status=order['status'],workflow_status='COMPLETED',
                        last_error=None,recovery_node=None,updated_at=now())
        except AgentFailure as exc:
            self.event(state,'verify_purchase_order','ERROR',start,error_type=exc.code,po_no=state.get('po_no'))
            return dict(workflow_status='ERROR',last_error=exc.code,recovery_node='verify_purchase_order',updated_at=now())

    def recovery_wait(self,state):
        self.event(state,'recovery_wait','INTERRUPT',checkpoint_status='PERSISTED',error_type=state['last_error'])
        answer=RecoveryDecision.model_validate(interrupt(dict(type='RECOVERY_REQUIRED',workflow_id=state['workflow_id'],
            failed_node=state['recovery_node'],error_type=state['last_error'],retry_count=state['retry_count'])))
        if answer.workflow_id!=state['workflow_id']:raise AgentFailure('WORKFLOW_ID_MISMATCH')
        self.event(state,'recovery_wait','RESUME')
        return dict(retry_count=state['retry_count']+1,workflow_status='EXECUTING',updated_at=now())
