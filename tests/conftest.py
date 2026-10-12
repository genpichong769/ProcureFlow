from datetime import date, timedelta
from decimal import Decimal
import mysql.connector
import pytest
from config import get_settings
from db.connection import Database
from db.repositories.base import execute
from scripts.schema import TABLES, initialize
from services.procurement_service import ProcurementService
from services.rules import approval_level_resolution
import json


@pytest.fixture(scope='session')
def test_database():
    settings = get_settings().model_copy(update={'db_name':'procureflow_test'})
    assert settings.db_name == 'procureflow_test'
    # Tests require this dedicated local schema; connection failures FAIL, never silently skip.
    conn = mysql.connector.connect(**settings.connection_kwargs())
    initialize(conn)
    conn.close()
    return Database(settings)


@pytest.fixture
def db(test_database):
    assert test_database.settings.db_name == 'procureflow_test'
    with test_database.transaction() as conn:
        for table in reversed(TABLES):
            execute(conn,'DELETE FROM `'+table+'`')
        for d in (1,2):
            execute(conn,"INSERT INTO departments(id,department_code,department_name) VALUES(%s,%s,%s)",(d,f'DEP{d:03}',f'Department {d}'))
            execute(conn,"INSERT INTO employees(id,employee_no,employee_name,department_id,role) VALUES(%s,%s,%s,%s,'EMPLOYEE')",(d,f'E{d}',f'Employee {d}',d))
            execute(conn,'INSERT INTO department_budgets(id,department_id,fiscal_year,total_budget) VALUES(%s,%s,%s,%s)',(d,d,date.today().year,1000000 if d==1 else 100))
        for p in (1,2,3):
            execute(conn,"INSERT INTO products(id,product_code,product_name,category,specification,reference_price) VALUES(%s,%s,%s,%s,'standard',%s)",(p,f'PRD{p:05}',f'Product {p}','IT' if p<3 else 'OFFICE',p*100))
        for s in range(1,8):
            status = 'SUSPENDED' if s==4 else 'BLACKLISTED' if s==5 else 'ACTIVE'
            execute(conn,"INSERT INTO suppliers(id,supplier_code,supplier_name,category,profile,status,rating,on_time_rate,quality_rate) VALUES(%s,%s,%s,'IT','A',%s,4.9,0.985,0.995)",(s,f'S{s}',f'Supplier {s}',status))
            for k,kind in enumerate(('BUSINESS_LICENSE','QUALITY_CERT')):
                qstate = 'REVOKED' if s==6 and k==1 else 'EXPIRED' if s==7 and k==1 else 'ACTIVE'
                end = date.today()-timedelta(days=1) if qstate=='EXPIRED' else date.today()+timedelta(days=365)
                execute(conn,'INSERT INTO supplier_qualifications(supplier_id,qualification_type,certificate_no,valid_from,valid_until,status) VALUES(%s,%s,%s,%s,%s,%s)',(s,kind,f'CERT{s}{k}',date.today()-timedelta(days=365),end,qstate))
            execute(conn,"INSERT INTO supplier_performance(supplier_id,period,total_orders,on_time_orders,delayed_orders,accepted_orders,quality_issue_orders,average_delivery_days,average_price_index) VALUES(%s,'2026-01',100,98,2,99,1,3,1.1)",(s,))
        for q,s,p,price,quantity,days,status,start,end in [
            (1,1,1,100,1000,3,'ACTIVE',-30,365),(2,2,1,90,1000,4,'ACTIVE',-30,365),
            (3,3,1,110,1000,5,'ACTIVE',-30,365),(11,1,2,200,1000,3,'ACTIVE',-30,365),
            (12,2,2,180,1000,4,'ACTIVE',-30,365),(13,3,2,220,1000,5,'ACTIVE',-30,365),
            (20,1,1,50,1000,3,'ACTIVE',-30,-1),(21,1,1,50,1,3,'ACTIVE',-30,365),
            (22,4,1,50,1000,3,'ACTIVE',-30,365),(23,5,1,50,1000,3,'ACTIVE',-30,365),
            (24,1,1,50,1000,3,'ACTIVE',1,365),(25,1,1,50,1000,60,'ACTIVE',-30,365),
            (26,6,1,50,1000,3,'ACTIVE',-30,365),(27,7,1,50,1000,3,'ACTIVE',-30,365)]:
            execute(conn,'INSERT INTO supplier_quotes(id,supplier_id,product_id,unit_price,available_quantity,delivery_days,status,valid_from,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (q,s,p,price,quantity,days,status,date.today()+timedelta(days=start),date.today()+timedelta(days=end)))
        for low,high in [(0,5000),(5000,50000),(50000,200000),(200000,None)]:
            execute(conn,'INSERT INTO approval_rules(min_amount,max_amount,approval_chain_json,enabled) VALUES(%s,%s,%s,TRUE)',(low,high,json.dumps(approval_level_resolution(max(low,1)))))
        execute(conn,"INSERT INTO procurement_rules(rule_code,rule_name,rule_type,category,rule_config_json,priority) VALUES('THREE_QUOTES','Three quotes','MINIMUM_QUOTES','IT',%s,10)",(json.dumps({'threshold':'100000','minimum':3}),))
    yield test_database
    with test_database.transaction() as conn:
        for table in reversed(TABLES):
            execute(conn,'DELETE FROM `'+table+'`')


@pytest.fixture
def service(db):
    return ProcurementService(db)


@pytest.fixture
def request_factory(service):
    def create(department=1, quantity=2, unit_price='120.00', two_items=True):
        items = [dict(product_id=1,quantity=quantity,max_unit_price=unit_price)]
        if two_items:
            items.append(dict(product_id=2,quantity=1,max_unit_price='240.00'))
        return service.create_purchase_request(department,department,date.today()+timedelta(days=30),'Test procurement',items)
    return create


@pytest.fixture
def approved(db,service,request_factory):
    request = request_factory()
    service.budget.reserve(request['id'])
    # Trusted historical fixture only: Phase 1 exposes no approval decision tool.
    with db.transaction() as conn:
        execute(conn,"UPDATE purchase_requests SET status='APPROVED' WHERE id=%s",(request['id'],))
    return service.get_purchase_request(request['id'])


@pytest.fixture
def order_args(approved):
    return dict(request_id=approved['id'],supplier_id=1,items=[dict(product_id=1,quote_id=1,quantity=2),dict(product_id=2,quote_id=11,quantity=1)])
