from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest
from db.repositories.base import all_rows
from services.budget_service import BudgetService
from services.errors import BusinessError


def test_normal_budget(db):
    s = BudgetService(db)
    assert s.get_department_budget('DEP001')['available_budget'] == 1000000
    assert s.check_budget(1,100)['passed']
    assert not s.check_budget(2,101)['passed']
    assert s.get_budget_transactions(1) == []


def test_missing_department(db):
    with pytest.raises(BusinessError,match='部门不存在'):
        BudgetService(db).get_department_budget(999)


def test_reserve_release_and_retry(service,request_factory):
    r = request_factory()
    service.budget.reserve(r['id'])
    service.budget.reserve(r['id'])
    budget = service.budget.get_department_budget(1)
    assert budget['reserved_budget'] == 480
    assert budget['available_budget'] == 999520
    assert len(service.budget.get_budget_transactions(1)) == 1
    service.budget.release(r['id'])
    service.budget.release(r['id'])
    assert service.budget.get_department_budget(1)['reserved_budget'] == 0
    assert {t['transaction_type'] for t in service.budget.get_budget_transactions(1)} == {'RESERVE','RELEASE'}


def test_budget_insufficient_rolls_back(service,request_factory):
    r = request_factory(department=2)
    with pytest.raises(BusinessError,match='预算不足'):
        service.budget.reserve(r['id'])
    assert service.get_purchase_request(r['id'])['status'] == 'DRAFT'
    assert service.budget.get_budget_transactions(2) == []


def test_commit_exact_amount(service,order_args):
    po = service.create_purchase_order(**order_args)
    assert service.budget.get_department_budget(1)['reserved_budget'] == 400
    service.update_purchase_order_status(po['id'],'CONFIRMED')
    service.update_purchase_order_status(po['id'],'CONFIRMED')
    budget = service.budget.get_department_budget(1)
    assert budget['used_budget'] == 400 and budget['reserved_budget'] == 0
    tx = service.budget.get_budget_transactions(1)
    assert [t['amount'] for t in tx if t['transaction_type']=='COMMIT'] == [Decimal('400.00')]


def test_concurrent_reserves_do_not_overspend(service,request_factory):
    requests = [request_factory(quantity=1000,unit_price='600.00',two_items=False) for _ in range(2)]
    def reserve(request):
        try:
            service.budget.reserve(request['id'])
            return True
        except BusinessError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve,requests))
    assert sorted(results) == [False,True]
    assert service.budget.get_department_budget(1)['reserved_budget'] == 600000
