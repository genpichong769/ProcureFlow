import asyncio
from datetime import date,timedelta
import pytest
from agents.specialists import SupplierSourcingAgent
from agents.coordinator import hard_filter
from agents.schemas import ProcurementRequirement
from .helpers import FakeMCP,llm,requirement,candidate


@pytest.mark.parametrize('empty',[False,True])
def test_sourcing_reads_facts_and_performance(empty):
    row=candidate().model_dump(mode='json')
    for name in ('supplier_code','performance','price_score','delivery_score','on_time_score','quality_score','final_score'):row.pop(name)
    mcp=FakeMCP(dict(search_supplier_quotes=[] if empty else [row],get_supplier_detail=dict(supplier_code='SUP0001'),get_supplier_performance=[{'total_orders':100}]))
    result=asyncio.run(SupplierSourcingAgent(llm(),mcp).run(dict(request_id='TEST',**requirement())))
    assert result.candidate_count==(0 if empty else 1)
    if not empty:assert result.candidates[0].performance==[{'total_orders':100}]


@pytest.mark.parametrize('changes',[
    {'supplier_status':'BLACKLISTED'},{'available_quantity':9},{'quote_valid_until':date.today()-timedelta(days=1)},
    {'delivery_days':8},{'total_price':'2001'},{'total_price':'999'},{'product_code':'PRD99999'},
])
def test_coordinator_hard_filter_rejects(changes):
    req=ProcurementRequirement(request_id='TEST',**requirement())
    assert hard_filter([candidate(**changes)],req)==[]


def test_boundary_stock_deadline_price_and_expiry_allowed():
    req=ProcurementRequirement(request_id='TEST',**requirement(max_total_amount='1000'))
    c=candidate(available_quantity=10,delivery_days=7,quote_valid_until=date.today())
    assert hard_filter([c],req)==[c]
