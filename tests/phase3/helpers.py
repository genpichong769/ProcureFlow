import sqlite3
from datetime import date,timedelta
from decimal import Decimal
from langgraph.checkpoint.sqlite import SqliteSaver
from config import get_settings
from workflow.graph import ProcurementWorkflow


def proposal(chain=None):
    chain=chain or ['部门经理']
    candidate=dict(quote_id=1,supplier_id=1,supplier_code='SUP0001',supplier_name='Fixture supplier',supplier_status='ACTIVE',
        product_id=1,product_code='PRD00001',product_name='Fixture product',category='IT',unit_price='100.00',total_price='1000.00',
        available_quantity=100,delivery_days=3,quote_valid_until=(date.today()+timedelta(days=30)).isoformat(),
        on_time_rate='0.98',quality_rate='0.99',performance=[],price_score='100',delivery_score='100',on_time_score='98',quality_score='99',final_score='99.35')
    compliance=dict(request_id='IGNORED',supplier_id=1,compliance_passed=True,approval_chain=chain,warnings=[],failed_rules=[],required_quote_count=0,qualifications=[])
    return dict(request_id='IGNORED',requirement=dict(department_code='DEP001',product_name=None,product_code='PRD00001',quantity=10,
        max_unit_price=None,max_total_amount='2000.00',max_delivery_days=7,required_delivery_date=None,category=None,reason='fixture',supplier_id=None,
        request_id='IGNORED'),budget_result=dict(request_id='IGNORED',department_code='DEP001',total_budget='10000',used_budget='1000',reserved_budget='1000',
        available_budget='8000',requested_amount='2000',budget_ok=True,remaining_after_purchase='6000',reason='fixture'),all_candidates=[candidate],
        qualified_candidates=[candidate],recommended_supplier=candidate,compliance_result=compliance,compliance_results=[compliance],
        recommendation_reason='fixture evidence',status='READY_FOR_APPROVAL',missing_fields=[],warnings=[],error_type=None)


class FakeTransport:
    def __init__(self,data=None):self.data=data or proposal();self.calls=[]
    async def call(self,role,payload):
        self.calls.append((role,payload));value={**self.data,'request_id':payload['request_id']}
        value['requirement']={**value['requirement'],'request_id':payload['request_id']}
        value['budget_result']={**value['budget_result'],'request_id':payload['request_id']}
        value['compliance_result']={**value['compliance_result'],'request_id':payload['request_id']}
        value['compliance_results']=[value['compliance_result']]
        return value


class FakeMCP:
    def __init__(self):self.calls=[];self.request_id=900001;self.status='DRAFT';self.approvals={};self.order=None
    async def call(self,name,args):
        self.calls.append((name,args))
        if name=='validate_requester':return dict(id=args['requester_id'],employee_no='E4',role='EMPLOYEE',department_id=1,department_code='DEP001')
        if name=='create_purchase_request':
            self.status='DRAFT';return self.request(args)
        if name=='submit_purchase_request':self.status='PENDING_APPROVAL';return self.request()
        if name=='validate_approver':return dict(id=args['approver_id'],employee_no='E',role=args['required_role'],status='ACTIVE')
        if name=='record_approval':
            self.approvals.setdefault(args['approval_level'],dict(request_id=self.request_id,approver_id=args['approver_id'],
                approval_level=args['approval_level'],decision='APPROVED' if args['decision']=='APPROVE' else 'REJECTED',comment=args['comment'],decided_at='2026-10-11T00:00:00'))
            return self.approvals[args['approval_level']]
        if name=='release_request_budget':return {**self.request(),'released_amount':'2000.00'}
        if name=='set_purchase_request_approval':self.status=args['status'];return self.request()
        if name=='create_purchase_order':
            if self.order:return self.order
            self.order=dict(id=800001,po_no='P3TEST-PO',request_id=self.request_id,department_id=1,supplier_id=1,
                total_amount='1000.00',status='CREATED',items=[dict(product_id=1,quote_id=1,quantity=10,unit_price='100.00',total_price='1000.00')])
            return self.order
        if name=='update_purchase_order_status':self.order={**self.order,'status':'CONFIRMED'};return self.order
        if name=='get_purchase_order':return self.order
        raise AssertionError(name)
    def request(self,args=None):
        args=args or {};return dict(id=self.request_id,request_no=args.get('request_no','P3TEST-REQ'),requester_id=4,department_id=1,
            fiscal_year=2026,expected_budget='2000.00',required_delivery_date=(date.today()+timedelta(days=7)).isoformat(),
            reason='fixture',status=self.status,items=[dict(product_id=1,quantity=10,max_unit_price='200.00')])


def workflow(name,chain=None,mcp=None):
    directory=get_settings().require_persistent_path(get_settings().langgraph_dir/'tests');directory.mkdir(parents=True,exist_ok=True)
    path=directory/(name+'.sqlite')
    if path.exists():path.unlink()
    connection=sqlite3.connect(path,check_same_thread=False);saver=SqliteSaver(connection);saver.setup()
    backend=mcp or FakeMCP()
    graph=ProcurementWorkflow(connection=connection,checkpointer=saver)
    graph.nodes.transport=FakeTransport(proposal(chain));graph.nodes.mcp=backend
    return graph,backend,path
