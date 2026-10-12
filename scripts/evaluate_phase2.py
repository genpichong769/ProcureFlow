"""Fixed real-entity scenarios + independent read-only SQL oracle + actual Qwen/A2A/MCP evaluation.
SQL exists only in this offline evaluation harness, never in agents.
"""
import argparse
import asyncio
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from uuid import uuid4
from config import ROOT, get_settings
from db.connection import database
from db.repositories.base import all_rows
from mcp_server.common import serialize
from agents.a2a_transport import A2ATransport
from agents.common import AgentFailure


class Oracle:
    def __init__(self):
        with database.transaction() as conn:
            self.products={r['product_code']:r for r in all_rows(conn,'SELECT * FROM products')}
            self.suppliers={r['id']:r for r in all_rows(conn,'SELECT * FROM suppliers')}
            self.quotes=all_rows(conn,'SELECT * FROM supplier_quotes ORDER BY id')
            self.quals=all_rows(conn,'SELECT * FROM supplier_qualifications')
            self.rules=all_rows(conn,'SELECT * FROM procurement_rules WHERE enabled=1')
            self.approvals=all_rows(conn,'SELECT * FROM approval_rules WHERE enabled=1')
            self.budgets={r['department_code']:r for r in all_rows(conn,
                'SELECT d.department_code,b.* FROM departments d JOIN department_budgets b ON d.id=b.department_id WHERE fiscal_year=YEAR(CURDATE())')}
        self.byproduct={}
        self.byquote={q['id']:q for q in self.quotes}
        for q in self.quotes:self.byproduct.setdefault(q['product_id'],[]).append(q)
        self.byqual={}
        for q in self.quals:self.byqual.setdefault(q['supplier_id'],[]).append(q)

    def valid_quals(self,supplier_id,required=('BUSINESS_LICENSE','QUALITY_CERT')):
        found={q['qualification_type'] for q in self.byqual[supplier_id] if q['status']=='ACTIVE' and q['valid_from']<=date.today()<=q['valid_until']}
        return set(required)<=found

    def facts_match(self, candidate, requirement):
        q=self.byquote.get(candidate.get('quote_id'))
        if q is None:return False
        s=self.suppliers[q['supplier_id']];p=self.products[requirement['product_code']]
        expected=dict(supplier_id=s['id'],supplier_code=s['supplier_code'],supplier_name=s['supplier_name'],supplier_status=s['status'],
            product_id=q['product_id'],product_code=p['product_code'],product_name=p['product_name'],category=p['category'],
            unit_price=q['unit_price'],total_price=q['unit_price']*requirement['quantity'],available_quantity=q['available_quantity'],
            delivery_days=q['delivery_days'],quote_valid_until=q['valid_until'].isoformat(),on_time_rate=s['on_time_rate'],quality_rate=s['quality_rate'])
        return all(k in candidate and (Decimal(str(candidate[k]))==v if isinstance(v,Decimal) else candidate[k]==v) for k,v in expected.items())

    def candidates(self,r):
        p=self.products[r['product_code']]
        quantity=r['quantity']; cap=Decimal(r['max_total_amount'])
        return [q for q in self.byproduct[p['id']] if q['status']=='ACTIVE'
            and q['valid_from']<=date.today()<=q['valid_until']
            and self.suppliers[q['supplier_id']]['status']=='ACTIVE'
            and self.valid_quals(q['supplier_id']) and q['available_quantity']>=quantity
            and q['unit_price']*quantity<=cap and q['delivery_days']<=r['max_delivery_days']
            and ('max_unit_price' not in r or q['unit_price']<=Decimal(r['max_unit_price']))]

    def compliance(self,supplier_id,category,amount,count):
        s=self.suppliers[supplier_id]
        needed=3 if amount>100000 else 0
        passed=s['status']=='ACTIVE' and s['category']==category and self.valid_quals(supplier_id) and count>=needed
        for rule in self.rules:
            if rule['category'] not in (category,None,'*') or not (rule['min_amount']<=amount and (rule['max_amount'] is None or amount<rule['max_amount'])): continue
            c=json.loads(rule['rule_config_json']); kind=rule['rule_type']
            if kind=='MINIMUM_QUOTES' and amount>Decimal(c['threshold']):
                needed=max(needed,c['minimum']);passed=passed and count>=c['minimum']
            elif kind=='REQUIRED_QUALIFICATIONS':passed=passed and self.valid_quals(supplier_id,c['required'])
            elif kind=='MAX_AMOUNT':passed=passed and amount<=Decimal(c['limit'])
            elif kind=='SUPPLIER_STATUS':passed=passed and s['status']=='ACTIVE'
        chain=next(json.loads(a['approval_chain_json']) for a in self.approvals if a['min_amount']<=amount and (a['max_amount'] is None or amount<a['max_amount']))
        return dict(supplier_id=supplier_id,compliance_passed=passed,required_quote_count=needed,approval_chain=chain)

    def expected(self,scenario):
        r=scenario['requirement']
        out=dict(status='NEED_MORE_INFORMATION',budget=None,candidates=None,compliance=None,qualified=[],winner=None)
        if scenario['kind']=='missing':return out
        b=self.budgets[r['department_code']];amount=Decimal(r['max_total_amount'])
        available=b['total_budget']-b['used_budget']-b['reserved_budget']
        out['budget']=dict(total_budget=b['total_budget'],used_budget=b['used_budget'],reserved_budget=b['reserved_budget'],available_budget=available,
            requested_amount=amount,budget_ok=available>=amount,remaining_after_purchase=available-amount)
        if available<amount:out['status']='NO_BUDGET';return out
        candidates=self.candidates(r);out['candidates']=candidates
        category=self.products[r['product_code']]['category']
        targets=[q for q in candidates if not r.get('supplier_id') or q['supplier_id']==r['supplier_id']]
        count=len({q['supplier_id'] for q in candidates})
        comps=[self.compliance(q['supplier_id'],category,q['unit_price']*r['quantity'],count) for q in targets]
        if not targets and r.get('supplier_id'):comps=[self.compliance(r['supplier_id'],category,amount,count)]
        out['compliance']=comps
        good=[q for q,c in zip(targets,comps) if c['compliance_passed']]
        out['qualified']=good
        out['status']='READY_FOR_APPROVAL' if good else 'COMPLIANCE_FAILED' if any(not c['compliance_passed'] for c in comps) else 'NO_SUPPLIER'
        if good:
            price=min(q['unit_price'] for q in good);days=min(q['delivery_days'] for q in good)
            s=get_settings();weights=[Decimal(str(getattr(s,'score_'+n+'_weight'))) for n in ('price','delivery','on_time','quality')]
            def key(q):
                sup=self.suppliers[q['supplier_id']]
                values=[price/q['unit_price']*100,Decimal(days)/q['delivery_days']*100,sup['on_time_rate']*100,sup['quality_rate']*100]
                score=sum(w*v for w,v in zip(weights,values)).quantize(Decimal('.000001'))
                return (-score,q['unit_price']*r['quantity'],q['delivery_days'],q['supplier_id'],q['id'])
            out['winner']=min(good,key=key)['id']
        return out


def parse_matches(req, expected):
    for key,value in expected.items():
        actual=req.get(key)
        if value is None:
            if actual is not None:return False
        elif key in ('max_total_amount','max_unit_price'):
            if actual is None or Decimal(str(actual))!=Decimal(str(value)):return False
        elif actual!=value:return False
    return True


def build(oracle):
    scenarios=[]
    def add(kind,r,text=None):
        i=len(scenarios)+1
        if text is None:
            templates=[
                '部门{department_code}采购产品{product_code}，数量{quantity}件，总预算{max_total_amount}元，{max_delivery_days}天内到货。',
                '请为{department_code}寻源：{product_code}共{quantity}件；交期不超过{max_delivery_days}天；总金额上限{max_total_amount}元。',
                '{department_code}需要{quantity}件{product_code}。最多花{max_total_amount}元，希望在{max_delivery_days}天内收到。']
            text=templates[i%3].format(**r)
            if r.get('supplier_id'):text+=f"仅考虑供应商ID {r['supplier_id']}，类别{r['category']}，请核验资质。"
        scenario=dict(id=f'S{i:02}',kind=kind,text=text,requirement=r)
        scenario['expected_status']=oracle.expected(scenario)['status']
        scenarios.append(scenario)
    def base(i):
        p=oracle.products[f'PRD{i:05}']
        return dict(department_code=f'DEP{(i-1)%5+1:03}',product_code=p['product_code'],quantity=10,
                    max_total_amount=str((p['reference_price']*15).quantize(Decimal('.01'))),max_delivery_days=30)
    for i in range(1,21):add('normal',base(i))
    for i in range(1,6):
        r=base(i);b=oracle.budgets[r['department_code']]
        r['max_total_amount']=str(b['total_budget']-b['used_budget']-b['reserved_budget']+1);add('no_budget',r)
    for i in range(1,6):r=base(i);r['max_delivery_days']=1;add('tight_delivery',r)
    for i in range(1,6):
        r=base(i);quotes=oracle.byproduct[i];r['quantity']=max(q['available_quantity'] for q in quotes)+1
        r['max_total_amount']=str(max(q['unit_price'] for q in quotes)*r['quantity']);add('no_stock',r)
    for i in range(1,6):
        r=base(i);r.update(supplier_id=60+i,category=oracle.products[r['product_code']]['category']);add('qualification',r)
    for i in range(1,6):
        r=base(i);r.update(quantity=1,max_total_amount='99999999.00',max_delivery_days=365)
        quotes=sorted(oracle.candidates(r),key=lambda q:q['unit_price'])
        r['quantity']=int((Decimal(100001)/quotes[0]['unit_price']).to_integral_value(rounding=ROUND_CEILING))
        r['max_total_amount']=str(quotes[1]['unit_price']*r['quantity'])
        add('insufficient_quotes',r)
    for i in range(1,6):
        r=dict(department_code=f'DEP{i:03}',product_code=f'PRD{i:05}',quantity=None,max_total_amount=None,max_delivery_days=None)
        add('missing',r,f"帮部门DEP{i:03}采购一些产品PRD{i:05}，数量、预算和交期尚未确定。")
    expected={'normal':'READY_FOR_APPROVAL','no_budget':'NO_BUDGET','tight_delivery':'NO_SUPPLIER','no_stock':'NO_SUPPLIER',
              'qualification':'COMPLIANCE_FAILED','insufficient_quotes':'COMPLIANCE_FAILED','missing':'NEED_MORE_INFORMATION'}
    assert len(scenarios)==50 and all(s['expected_status']==expected[s['kind']] for s in scenarios),'Dataset no longer meets frozen scenario prerequisites'
    path=get_settings().require_persistent_path(get_settings().generated_dir/'phase2/scenarios.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==scenarios,'Fixed scenarios changed; do not overwrite evaluation baseline'
    else:path.write_text(json.dumps(scenarios,ensure_ascii=False,indent=2),encoding='utf-8')
    return path,scenarios


async def evaluate(path,scenarios,oracle):
    run_id='EVAL-'+uuid4().hex[:12];outdir=ROOT/'reports/phase2';outdir.mkdir(parents=True,exist_ok=True)
    records=[];sem=asyncio.Semaphore(2)
    async def one(s):
        async with sem:
            rid=run_id+'-'+s['id']
            try:actual=await A2ATransport().call('procurement',dict(request_id=rid,text=s['text']))
            except AgentFailure as exc:actual=dict(status='ERROR',error_type=exc.code)
            expected=oracle.expected(s);checks={}
            checks['task_success_rate']=actual['status']==expected['status']
            req=actual.get('requirement') or {}
            checks['requirement_parse_accuracy']=parse_matches(req,s['requirement'])
            if expected['budget'] is not None:
                a=actual.get('budget_result') or {}
                checks['budget_accuracy']=all(k in a and (Decimal(str(a[k]))==v if isinstance(v,Decimal) else a[k]==v) for k,v in expected['budget'].items())
            if expected['candidates'] is not None:
                checks['supplier_filter_accuracy']=({q['id'] for q in expected['candidates']}=={q['quote_id'] for q in actual.get('all_candidates',[])}
                    and {q['id'] for q in expected['qualified']}=={q['quote_id'] for q in actual.get('qualified_candidates',[])}
                    and all(oracle.facts_match(q,s['requirement']) for q in actual.get('all_candidates',[])))
            if expected['compliance']:
                a=actual.get('compliance_results',[]);e=expected['compliance']
                # Candidate order is irrelevant; compare full result tuple, including required count and approval chain.
                def norm(c):return (c['supplier_id'],c['compliance_passed'],c['required_quote_count'],tuple(c['approval_chain']))
                checks['compliance_accuracy']=sorted(map(norm,a))==sorted(map(norm,e))
            if expected['winner']:
                winner=actual.get('recommended_supplier') or {}
                checks['recommendation_validity']=(winner.get('quote_id')==expected['winner'] and oracle.facts_match(winner,s['requirement'])
                    and actual.get('compliance_result',{}).get('compliance_passed') is True)
            records.append(dict(scenario_id=s['id'],kind=s['kind'],expected_status=expected['status'],checks=checks,proposal=actual))
            (outdir/(run_id+'-partial.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
            print(s['id'],s['kind'],actual['status'], 'PASS' if all(checks.values()) else 'FAIL',flush=True)
    await asyncio.gather(*(one(s) for s in scenarios))
    metrics={}
    for name in sorted({k for r in records for k in r['checks']}):
        outcomes=[r['checks'][name] for r in records if name in r['checks']]
        metrics[name]=dict(numerator=sum(outcomes),denominator=len(outcomes),rate=sum(outcomes)/len(outcomes))
    tracepath=get_settings().logs_dir/'agents/trace.jsonl'
    traces=[json.loads(line) for line in tracepath.read_text(encoding='utf-8').splitlines() if line.strip()]
    traces=[t for t in traces if t['request_id'].startswith(run_id)]
    for name,action in [('tool_call_success_rate','MCP_CALL'),('a2a_call_success_rate','A2A_CALL')]:
        rows=[t for t in traces if t['action']==action];success=sum(t['status']=='SUCCESS' for t in rows)
        metrics[name]=dict(numerator=success,denominator=len(rows),rate=success/len(rows) if rows else None)
    report=dict(run_id=run_id,completed_at=datetime.now(timezone.utc).isoformat(),model=get_settings().qwen_model,
        scenario_file=str(path),scenario_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scenario_count=len(records),
        categories=dict(Counter(s['kind'] for s in scenarios)),metrics=metrics,
        result='PASS' if all(m['rate']==1 for m in metrics.values()) else 'FAIL',
        failures=[r['scenario_id'] for r in records if not all(r['checks'].values())],records=sorted(records,key=lambda r:r['scenario_id']))
    (outdir/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (outdir/'evaluation-trace.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in traces),encoding='utf-8')
    print(json.dumps(dict(result=report['result'],metrics=metrics),ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--build-only',action='store_true');args=parser.parse_args()
    oracle=Oracle();path,scenarios=build(oracle)
    if args.build_only:print(json.dumps(dict(path=str(path),count=len(scenarios),categories=dict(Counter(s['kind'] for s in scenarios))),ensure_ascii=False))
    else:
        result=asyncio.run(evaluate(path,scenarios,oracle))
        raise SystemExit(0 if result['result']=='PASS' else 1)
