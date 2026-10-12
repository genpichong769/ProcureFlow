from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import pytest
from pydantic import ValidationError
from mysql.connector import IntegrityError
from db.repositories.base import all_rows, one, execute
from services.errors import BusinessError


def test_create_and_query_request(service,request_factory):
    r = request_factory()
    assert r['status']=='DRAFT' and r['expected_budget']==480 and len(r['items'])==2
    assert service.get_purchase_request(r['id'])==r


def test_success_real_inserts_and_requery(db,service,order_args):
    po = service.create_purchase_order(**order_args)
    assert po['status']=='CREATED' and po['total_amount']==400 and len(po['items'])==2
    assert service.get_purchase_order(po['id']) == po
    assert service.get_purchase_request(order_args['request_id'])['status']=='ORDER_CREATED'
    with db.transaction() as conn:
        assert one(conn,'SELECT COUNT(*) n FROM purchase_orders')['n']==1
        assert one(conn,'SELECT available_quantity n FROM supplier_quotes WHERE id=1')['n']==998


@pytest.mark.parametrize('status',['DRAFT','PENDING_APPROVAL','REJECTED','CANCELLED','ORDER_CREATED'])
def test_nonapproved_rejected(db,service,order_args,status):
    with db.transaction() as conn:
        execute(conn,'UPDATE purchase_requests SET status=%s WHERE id=%s',(status,order_args['request_id']))
    with pytest.raises(BusinessError,match='已批准'):
        service.create_purchase_order(**order_args)


def test_transaction_rollback_after_item_insert(db,service,order_args,monkeypatch):
    original = service.repo.insert_order_item
    def fault(conn,order_id,item,price):
        original(conn,order_id,item,price)
        if item.product_id==2:
            raise RuntimeError('injected failure after real second item INSERT')
    monkeypatch.setattr(service.repo,'insert_order_item',fault)
    with pytest.raises(RuntimeError):
        service.create_purchase_order(**order_args)
    with db.transaction() as conn:
        assert one(conn,'SELECT COUNT(*) n FROM purchase_orders')['n']==0
        assert one(conn,'SELECT COUNT(*) n FROM purchase_order_items')['n']==0
        assert one(conn,'SELECT available_quantity n FROM supplier_quotes WHERE id=1')['n']==1000
    assert service.get_purchase_request(order_args['request_id'])['status']=='APPROVED'
    assert service.budget.get_department_budget(1)['reserved_budget']==480


def test_rollback_after_budget_and_request_mutation(db,service,order_args,monkeypatch):
    original = service.repo.request_status
    def fault(*args):
        original(*args)
        raise RuntimeError('injected failure after request UPDATE and RELEASE')
    monkeypatch.setattr(service.repo,'request_status',fault)
    with pytest.raises(RuntimeError):
        service.create_purchase_order(**order_args)
    assert service.get_purchase_request(order_args['request_id'])['status']=='APPROVED'
    assert service.budget.get_department_budget(1)['reserved_budget']==480
    assert len(service.budget.get_budget_transactions(1))==1
    with db.transaction() as conn:
        assert one(conn,'SELECT COUNT(*) n FROM purchase_orders')['n']==0


def test_sequential_idempotency(service,order_args):
    po = service.create_purchase_order(**order_args)
    assert service.create_purchase_order(**order_args)==po
    assert service.create_purchase_order(order_args['request_id'])==po
    assert len(service.budget.get_budget_transactions(1))==2


def test_concurrent_idempotency(db,service,order_args):
    with ThreadPoolExecutor(max_workers=6) as pool:
        orders = list(pool.map(lambda _: service.create_purchase_order(**order_args),range(6)))
    assert len({p['id'] for p in orders})==1
    with db.transaction() as conn:
        assert one(conn,'SELECT COUNT(*) n FROM purchase_orders')['n']==1
        assert one(conn,'SELECT COUNT(*) n FROM purchase_order_items')['n']==2
    assert len(service.budget.get_budget_transactions(1))==2


def test_database_unique_constraint(db,service,order_args):
    po = service.create_purchase_order(**order_args)
    with pytest.raises(IntegrityError):
        with db.transaction() as conn:
            execute(conn,"INSERT INTO purchase_orders(po_no,request_id,department_id,supplier_id,total_amount,status) VALUES('DUP',%s,1,1,400,'CREATED')",(po['request_id'],))


def test_cancel_releases_budget_and_restores_stock(db,service,order_args):
    po = service.create_purchase_order(**order_args)
    result = service.update_purchase_order_status(po['id'],'CANCELLED')
    assert result['status']=='CANCELLED'
    assert service.update_purchase_order_status(po['id'],'CANCELLED')==result
    assert service.budget.get_department_budget(1)['reserved_budget']==0
    assert service.get_purchase_request(po['request_id'])['status']=='CANCELLED'
    with db.transaction() as conn:
        assert one(conn,'SELECT available_quantity n FROM supplier_quotes WHERE id=1')['n']==1000


@pytest.mark.parametrize('first,second',[('CONFIRMED','CANCELLED'),('CANCELLED','CONFIRMED'),('CONFIRMED','CREATED')])
def test_invalid_status_transition(service,order_args,first,second):
    po = service.create_purchase_order(**order_args)
    service.update_purchase_order_status(po['id'],first)
    with pytest.raises(BusinessError):
        service.update_purchase_order_status(po['id'],second)


def test_confirmation_rolls_back(db,service,order_args,monkeypatch):
    po = service.create_purchase_order(**order_args)
    def fault(*args):
        raise RuntimeError('injected failure after COMMIT ledger entry')
    monkeypatch.setattr(service.repo,'order_status',fault)
    with pytest.raises(RuntimeError):
        service.update_purchase_order_status(po['id'],'CONFIRMED')
    budget = service.budget.get_department_budget(1)
    assert budget['reserved_budget']==400 and budget['used_budget']==0
    assert service.get_purchase_order(po['id'])['status']=='CREATED'
    assert all(t['transaction_type']!='COMMIT' for t in service.budget.get_budget_transactions(1))


@pytest.mark.parametrize('mutation',['quantity','quote','product','empty','duplicate','unknown_field'])
def test_illegal_order_items(service,order_args,mutation):
    args = deepcopy(order_args)
    if mutation=='quantity': args['items'][0]['quantity']=3
    if mutation=='quote': args['items'][0]['quote_id']=2
    if mutation=='product': args['items'][0]['product_id']=3
    if mutation=='empty': args['items']=[]
    if mutation=='duplicate': args['items'].append(args['items'][0])
    if mutation=='unknown_field': args['items'][0]['unit_price']='0.01'
    with pytest.raises((BusinessError,ValidationError)):
        service.create_purchase_order(**args)


@pytest.mark.parametrize('supplier',[4,5])
def test_order_inactive_supplier(service,order_args,supplier):
    order_args['supplier_id']=supplier
    with pytest.raises(BusinessError,match='供应商不可用'):
        service.create_purchase_order(**order_args)


@pytest.mark.parametrize('quote_id',[20,21,24,25])
def test_order_expired_low_stock_future_slow_quote(service,order_args,quote_id):
    order_args['items'][0]['quote_id']=quote_id
    with pytest.raises(BusinessError):
        service.create_purchase_order(**order_args)


def test_order_recomputes_valid_quote_count(db,service,request_factory):
    request = request_factory(quantity=1000,unit_price='120.00',two_items=False)
    service.budget.reserve(request['id'])
    with db.transaction() as conn:
        execute(conn,"UPDATE purchase_requests SET status='APPROVED' WHERE id=%s",(request['id'],))
        execute(conn,'UPDATE supplier_quotes SET unit_price=110 WHERE id=1')
        execute(conn,"UPDATE suppliers SET status='SUSPENDED' WHERE id=3")
    with pytest.raises(BusinessError,match='MINIMUM_QUOTE_COUNT'):
        service.create_purchase_order(request['id'],1,[dict(product_id=1,quote_id=1,quantity=1000)])


def test_request_cross_department_rejected(service):
    with pytest.raises(BusinessError,match='不属于'):
        service.create_purchase_request(1,2,date.today()+timedelta(days=5),'test',[dict(product_id=1,quantity=1,max_unit_price='100')])
