"""The sole LangGraph in ProcureFlow: end-to-end procurement workflow orchestration."""
from datetime import datetime,timezone
from threading import Lock
from uuid import uuid4
from langgraph.graph import StateGraph,START,END
from langgraph.types import Command
from agents.common import AgentFailure
from workflow.state import ProcurementWorkflowState
from workflow.nodes import WorkflowNodes
from workflow.checkpoint import create_checkpointer
from workflow.routing import route_proposal,route_approval,check_more,route_operation,route_recovery
from workflow.approval import ApprovalDecision,RecoveryDecision
from workflow.trace import workflow_trace


class ProcurementWorkflow:
    def __init__(self,nodes=None,connection=None,checkpointer=None):
        self.connection,self.checkpointer=(connection,checkpointer) if checkpointer else create_checkpointer()
        self.nodes=nodes or WorkflowNodes()
        self.graph=self._compile()
        self._lock=Lock()

    def _compile(self):
        g=StateGraph(ProcurementWorkflowState)
        for name in ('build_proposal','create_purchase_request','reserve_budget','prepare_approval','human_approval',
                     'check_more_approvals','next_approval','release_budget','mark_request_rejected','mark_request_approved',
                     'execute_purchase','commit_budget','verify_purchase_order','recovery_wait'):
            g.add_node(name,getattr(self.nodes,name))
        g.add_edge(START,'build_proposal')
        g.add_conditional_edges('build_proposal',route_proposal,{'ready':'create_purchase_request','stop':END})
        g.add_edge('create_purchase_request','reserve_budget')
        g.add_conditional_edges('reserve_budget',lambda s:'ok' if s['workflow_status']=='PENDING_APPROVAL' else 'failed',{'ok':'prepare_approval','failed':END})
        g.add_conditional_edges('prepare_approval',lambda s:'human' if s['approval_chain'] else 'exempt',
                                {'human':'human_approval','exempt':'mark_request_approved'})
        g.add_conditional_edges('human_approval',route_approval,{'rejected':'release_budget','approved':'check_more_approvals'})
        g.add_edge('release_budget','mark_request_rejected');g.add_edge('mark_request_rejected',END)
        g.add_conditional_edges('check_more_approvals',check_more,{'more':'next_approval','done':'mark_request_approved'})
        g.add_edge('next_approval','human_approval');g.add_edge('mark_request_approved','execute_purchase')
        g.add_conditional_edges('execute_purchase',route_operation,{'success':'commit_budget','recover':'recovery_wait','failed':END})
        g.add_conditional_edges('commit_budget',route_operation,{'success':'verify_purchase_order','recover':'recovery_wait','failed':END})
        g.add_conditional_edges('verify_purchase_order',route_operation,{'success':END,'recover':'recovery_wait','failed':END})
        g.add_conditional_edges('recovery_wait',route_recovery,{
            'execute_purchase':'execute_purchase','commit_budget':'commit_budget','verify_purchase_order':'verify_purchase_order'})
        return g.compile(checkpointer=self.checkpointer)

    @staticmethod
    def new_id(test=False):
        prefix='P3TEST-' if test else 'WF-'
        return prefix+datetime.now().strftime('%Y%m%d')+'-'+uuid4().hex[:12]

    @staticmethod
    def config(workflow_id):return {'configurable':{'thread_id':workflow_id}}

    def start(self,user_query,requester_id,workflow_id=None,test=False):
        workflow_id=workflow_id or self.new_id(test)
        if self.exists(workflow_id):raise AgentFailure('WORKFLOW_ALREADY_EXISTS')
        timestamp=datetime.now(timezone.utc).isoformat()
        state=ProcurementWorkflowState(workflow_id=workflow_id,user_query=user_query,requester_id=requester_id,
            requirement=None,proposal=None,budget_result=None,supplier_candidates=[],qualified_candidates=[],
            recommended_supplier=None,compliance_result=None,request_id=None,request_no=None,request_record=None,
            approval_chain=[],current_approval_index=0,approval_history=[],approval_status='NOT_STARTED',
            reserved_amount=None,purchase_order_id=None,po_no=None,purchase_order_status=None,purchase_order=None,
            workflow_status='INITIALIZED',proposal_status=None,retry_count=0,recovery_node=None,last_error=None,
            created_at=timestamp,updated_at=timestamp)
        with self._lock:self.graph.invoke(state,self.config(workflow_id))
        workflow_trace(workflow_id,'graph','START_OR_INTERRUPT',checkpoint_status='PERSISTED')
        return self.get(workflow_id)

    def _snapshot(self,workflow_id):
        snapshot=self.graph.get_state(self.config(workflow_id))
        if not snapshot.values:raise AgentFailure('WORKFLOW_NOT_FOUND')
        return snapshot

    def exists(self,workflow_id):
        return bool(self.graph.get_state(self.config(workflow_id)).values)

    def get(self,workflow_id):
        snapshot=self._snapshot(workflow_id)
        interrupts=[i.value for task in snapshot.tasks for i in task.interrupts]
        return dict(state=dict(snapshot.values),interrupts=interrupts,next=list(snapshot.next),
                    checkpoint_persisted=True)

    def resume(self,decision):
        parsed=ApprovalDecision.model_validate(decision);snapshot=self._snapshot(parsed.workflow_id)
        interrupts=[i.value for task in snapshot.tasks for i in task.interrupts]
        if not interrupts or interrupts[0].get('type')!='HUMAN_APPROVAL':raise AgentFailure('WORKFLOW_NOT_WAITING_APPROVAL')
        with self._lock:self.graph.invoke(Command(resume=parsed.model_dump(mode='json')),self.config(parsed.workflow_id))
        return self.get(parsed.workflow_id)

    def retry(self,workflow_id):
        snapshot=self._snapshot(workflow_id);interrupts=[i.value for task in snapshot.tasks for i in task.interrupts]
        if not interrupts or interrupts[0].get('type')!='RECOVERY_REQUIRED':raise AgentFailure('WORKFLOW_NOT_RECOVERABLE')
        command=RecoveryDecision(workflow_id=workflow_id,retry=True)
        with self._lock:self.graph.invoke(Command(resume=command.model_dump(mode='json')),self.config(workflow_id))
        return self.get(workflow_id)

    def close(self):
        if self.connection:self.connection.close()
