"""Deterministic correlated procurement history; no network / LLM required.
The fixed reference date is part of the versioned dataset, never date.today().
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
from config import ROOT, get_settings
from scripts.schema import TABLES
from services.rules import approval_level_resolution

SEED = 42
AS_OF = date(2026,10,2)
CATEGORIES = ['IT','OFFICE','FURNITURE','NETWORK','LAB','SAFETY','PACKAGING','ELECTRICAL',
              'MECHANICAL','CLEANING','PRINT','STORAGE','TOOLS','LIGHTING','MEASUREMENT',
              'COMMUNICATION','COOLING','POWER','MAINTENANCE','CONSUMABLES']
BASE_PROFILES = {'A':(1.12,3,0.985,0.995), 'B':(0.88,15,0.88,0.96),
                 'C':(1.00,8,0.91,0.87), 'D':(0.94,12,0.80,0.83)}


def encode(value):
    if isinstance(value,Decimal):
        return str(value)
    if isinstance(value,(date,datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def generate(output):
    output = get_settings().require_persistent_path(output)
    output.mkdir(parents=True,exist_ok=True)
    rng = random.Random(SEED)
    rows = {table:[] for table in TABLES}

    def add(table, **fields):
        row = dict(id=len(rows[table])+1,**fields)
        rows[table].append(row)
        return row

    def dec(value):
        return Decimal(str(value)).quantize(Decimal('0.01'))

    start = datetime(2026,1,2,9)
    for d in range(1,31):
        add('departments',department_code=f'DEP{d:03}',department_name=f'事业部{d:02}',status='ACTIVE',created_at=start)
    roles = ['部门经理','采购经理','财务负责人'] + ['EMPLOYEE']*47
    for e in range(1500):
        add('employees',employee_no=f'EMP{e+1:05}',employee_name=f'员工{e+1:04}',department_id=e//50+1,role=roles[e%50],status='ACTIVE')
    budgets = {}
    for d in range(1,31):
        for year in (2024,2025,2026):
            budgets[d,year] = add('department_budgets',department_id=d,fiscal_year=year,total_budget=Decimal('1000000000.00'),used_budget=Decimal('0.00'),reserved_budget=Decimal('0.00'),updated_at=start)
    for p in range(5000):
        cat = CATEGORIES[p%20]
        add('products',product_code=f'PRD{p+1:05}',product_name=f'{cat}采购物料{p+1:05}',category=cat,
            specification=f'企业标准规格-{p%12+1}',reference_price=dec(rng.randrange(2000,500000)/100),status='ACTIVE')
    by_category = defaultdict(list)
    for s in range(800):
        profile = 'ABCD'[(s//20)%4]
        _,_,on_time,quality = BASE_PROFILES[profile]
        status = ('SUSPENDED' if s%3 else 'BLACKLISTED') if profile == 'D' and (s//80)%2 == 0 else 'ACTIVE'
        row = add('suppliers',supplier_code=f'SUP{s+1:04}',supplier_name=f'{profile}型供应商{s+1:04}',category=CATEGORIES[s%20],
            profile=profile,status=status,rating=dec(5*(on_time+quality)/2),on_time_rate=Decimal(str(on_time)),quality_rate=Decimal(str(quality)),created_at=datetime(2024,1,1))
        by_category[row['category']].append(row)
        for n,kind in enumerate(('BUSINESS_LICENSE','QUALITY_CERT','ENVIRONMENT_CERT')):
            state,until = 'ACTIVE',date(2027,12,31)
            if profile == 'D' and n == 1:
                state,until = ('EXPIRED',date(2025,12,31)) if s%2 else ('REVOKED',date(2027,12,31))
            elif profile == 'C' and n == 2:
                until = AS_OF + timedelta(days=10)
            add('supplier_qualifications',supplier_id=row['id'],qualification_type=kind,certificate_no=f'CERT-{s+1:04}-{n}',
                valid_from=date(2024,1,1),valid_until=until,status=state)
        for month in range(25):
            price,days,_,_ = BASE_PROFILES[profile]
            orders = rng.randint(40,150)
            on_time_count = min(orders,round(orders*max(0,min(1,rng.gauss(on_time,0.015)))))
            accepted = min(orders,round(orders*max(0,min(1,rng.gauss(quality,0.012)))))
            month_index = 2024*12+7+month
            add('supplier_performance',supplier_id=row['id'],period=f'{month_index//12:04}-{month_index%12+1:02}',
                total_orders=orders,on_time_orders=on_time_count,delayed_orders=orders-on_time_count,
                accepted_orders=accepted,quality_issue_orders=orders-accepted,
                average_delivery_days=dec(max(1,rng.gauss(days,0.8))),average_price_index=Decimal(str(price)))
    primary_quotes = {}
    for product in rows['products']:
        for j,supplier in enumerate(by_category[product['category']][:20]):
            factor,days,_,_ = BASE_PROFILES[supplier['profile']]
            expired = j in (4,9,14)
            price = dec(product['reference_price'] * Decimal(str(factor*rng.uniform(0.96,1.04))))
            quote = add('supplier_quotes',supplier_id=supplier['id'],product_id=product['id'],unit_price=price,
                available_quantity=(rng.randint(0,2) if j in (6,11) else rng.randint(500,2000)),
                delivery_days=(60 if j in (7,12) else max(1,days+rng.randint(-1,2))),
                valid_from=date(2025,1,1),valid_until=date(2025,12,31) if expired else date(2027,12,31),
                status='EXPIRED' if expired else 'ACTIVE',created_at=datetime(2025,1,1))
            if j == 0:
                primary_quotes[product['id']] = quote
    for cat in CATEGORIES:
        for kind,config in [('SUPPLIER_STATUS',{'allowed':['ACTIVE']}),
                            ('REQUIRED_QUALIFICATIONS',{'required':['BUSINESS_LICENSE','QUALITY_CERT']}),
                            ('MINIMUM_QUOTES',{'threshold':'100000.00','minimum':3}),
                            ('MAX_AMOUNT',{'limit':'100000000.00'})]:
            add('procurement_rules',rule_code=f'{cat}_{kind}',rule_name=f'{cat} {kind}',rule_type=kind,category=cat,
                min_amount='0.00',max_amount=None,rule_config_json=json.dumps(config,ensure_ascii=False),priority=10,enabled=1)
    for low,high in [(0,5000),(5000,50000),(50000,200000),(200000,None)]:
        chain = approval_level_resolution(Decimal(max(low,1)))
        add('approval_rules',min_amount=dec(low),max_amount=None if high is None else dec(high),approval_chain_json=json.dumps(chain,ensure_ascii=False),enabled=1)

    def event(request, kind, amount, when):
        budget = budgets[request['department_id'],request['fiscal_year']]
        if kind == 'RESERVE':
            budget['reserved_budget'] += amount
        else:
            budget['reserved_budget'] -= amount
            if kind == 'COMMIT':
                budget['used_budget'] += amount
        budget['updated_at'] = when
        add('budget_transactions',department_id=request['department_id'],fiscal_year=request['fiscal_year'],request_id=request['id'],transaction_type=kind,
            amount=amount,balance_after=budget['total_budget']-budget['used_budget']-budget['reserved_budget'],transaction_time=when,description=f'合成历史采购 {kind}')

    for r in range(1,30001):
        d = (r-1)%30+1
        p1 = rng.randint(1,4980)
        p2 = p1+20
        quote1,quote2 = primary_quotes[p1],primary_quotes[p2]
        quantity = rng.choices([1,5,10,25,50,100],weights=[10,15,25,25,15,10])[0]
        amount = dec((quote1['unit_price']+quote2['unit_price'])*quantity)
        when = start + timedelta(seconds=r*10)
        po_status = 'CONFIRMED' if r <= 20000 else 'CREATED' if r <= 23000 else 'CANCELLED'
        status = ('CANCELLED' if po_status == 'CANCELLED' else 'ORDER_CREATED') if r <= 25000 else (
            'APPROVED' if r<=26000 else 'PENDING_APPROVAL' if r<=27000 else 'REJECTED' if r<=28000 else 'DRAFT' if r<=29000 else 'CANCELLED')
        request = add('purchase_requests',request_no=f'PR-SEED42-{r:06}',requester_id=(d-1)*50+4+(r%47),department_id=d,fiscal_year=2026,
            expected_budget=amount,required_delivery_date=date(2026,2,1),reason=f'{CATEGORIES[(p1-1)%20]}部门周期补货',status=status,created_at=when,updated_at=when+timedelta(seconds=3))
        for p,q in [(p1,quote1),(p2,quote2)]:
            add('purchase_request_items',request_id=r,product_id=p,quantity=quantity,max_unit_price=q['unit_price'],max_total_price=q['unit_price']*quantity)
        if status != 'DRAFT':
            event(request,'RESERVE',amount,when)
            if status in ('CANCELLED','REJECTED'):
                event(request,'RELEASE',amount,when+timedelta(seconds=3))
            elif r <= 20000:
                event(request,'COMMIT',amount,when+timedelta(seconds=3))
        if status not in ('DRAFT','CANCELLED') or r<=25000:
            chain = approval_level_resolution(amount)
            for level,role in enumerate(chain,1):
                decision = 'PENDING' if status == 'PENDING_APPROVAL' else 'REJECTED' if status == 'REJECTED' and level == 1 else 'APPROVED'
                if status == 'REJECTED' and level > 1:
                    break
                approver = (d-1)*50+['部门经理','采购经理','财务负责人'].index(role)+1
                add('approval_records',request_id=r,approver_id=approver,approval_level=level,decision=decision,
                    comment='合成历史审批记录；不代表本阶段实现审批工作流',decided_at=None if decision=='PENDING' else when+timedelta(seconds=1))
        if r <= 25000:
            add('purchase_orders',po_no=f'PO-SEED42-{r:06}',request_id=r,department_id=d,supplier_id=quote1['supplier_id'],
                total_amount=amount,status=po_status,created_at=when+timedelta(seconds=2),updated_at=when+timedelta(seconds=3))
            for p,q in [(p1,quote1),(p2,quote2)]:
                add('purchase_order_items',purchase_order_id=r,product_id=p,quote_id=q['id'],quantity=quantity,unit_price=q['unit_price'],total_price=q['unit_price']*quantity)
    manifest = dict(version=1,seed=SEED,as_of=AS_OF.isoformat(),files={},counts={})
    for table in TABLES:
        path = output / (table+'.jsonl')
        with path.open('w',encoding='utf-8',newline='\n') as handle:
            for row in rows[table]:
                handle.write(json.dumps(row,default=encode,ensure_ascii=False,separators=(',',':'))+'\n')
        manifest['files'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['counts'][table] = len(rows[table])
    manifest['total_rows'] = sum(manifest['counts'].values())
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'seed':SEED,'total_rows':manifest['total_rows'],'counts':manifest['counts']},ensure_ascii=True))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=get_settings().generated_dir)
    generate(parser.parse_args().output)
