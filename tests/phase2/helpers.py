from contextlib import asynccontextmanager
from datetime import date,timedelta
from unittest.mock import AsyncMock
from agents.schemas import SupplierCandidate,RequirementFields,ExplanationPlan
from agents.common import AgentFailure


def requirement(**updates):
    r=dict(department_code='DEP001',product_code='PRD00001',quantity=10,max_total_amount='2000.00',max_delivery_days=7)
    r.update(updates);return r


def candidate(**updates):
    data=dict(quote_id=1,supplier_id=1,supplier_code='SUP0001',supplier_name='Fixture supplier',supplier_status='ACTIVE',
        product_id=1,product_code='PRD00001',product_name='Fixture product',category='IT',unit_price='100.00',total_price='1000.00',
        available_quantity=100,delivery_days=3,quote_valid_until=date.today()+timedelta(days=30),on_time_rate='.98',quality_rate='.99')
    data.update(updates);return SupplierCandidate(**data)


def llm(fields=None):
    gateway=AsyncMock()
    gateway.extract.return_value=RequirementFields(**(fields or requirement()))
    gateway.select_tools.side_effect=lambda names,*_:list(names)
    gateway.explanation.return_value=ExplanationPlan(factors=['PRICE','DELIVERY'])
    return gateway


def budget(ok=True):
    return dict(request_id='TEST',department_code='DEP001',total_budget='10000',used_budget='1000',reserved_budget='1000',
        available_budget='8000',requested_amount='2000',budget_ok=ok,remaining_after_purchase='6000',reason='deterministic fixture')


def compliance(passed=True,supplier_id=1):
    return dict(request_id='TEST',supplier_id=supplier_id,compliance_passed=passed,approval_chain=['部门经理'],warnings=[],
        failed_rules=[] if passed else [dict(passed=False,rule_code='SUPPLIER_QUALIFICATION',reason='invalid')],required_quote_count=0)


class FakeMCP:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def __call__(self,*args):return self
    @asynccontextmanager
    async def connect(self):yield self
    async def call(self,name,args):
        self.calls.append((name,args))
        value=self.responses[name]
        if isinstance(value,Exception):raise value
        return value
