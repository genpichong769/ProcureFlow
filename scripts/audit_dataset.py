"""Audit actual MySQL rows, not generated counters. Nonzero exit on any critical failure."""
import argparse
from datetime import date
import json
from pathlib import Path
from config import ROOT, get_settings
from db.connection import database
from db.repositories.base import all_rows, one
from db.repositories.budget_repository import BUDGET_QUERY
from db.repositories.supplier_repository import CANDIDATE_QUERY
from db.repositories.procurement_repository import ORDER_QUERY
from mcp_server.common import serialize
from scripts.schema import TABLES

CHECKS = {
 'order_item_totals': '''SELECT COUNT(*) n FROM purchase_orders p LEFT JOIN
 (SELECT purchase_order_id,SUM(total_price) total FROM purchase_order_items GROUP BY purchase_order_id) i
 ON i.purchase_order_id=p.id WHERE i.total IS NULL OR p.total_amount<>i.total''',
 'request_item_totals': '''SELECT COUNT(*) n FROM purchase_requests p LEFT JOIN
 (SELECT request_id,SUM(max_total_price) total FROM purchase_request_items GROUP BY request_id) i
 ON i.request_id=p.id WHERE i.total IS NULL OR p.expected_budget<>i.total''',
 'performance_arithmetic': '''SELECT COUNT(*) n FROM supplier_performance WHERE total_orders<0 OR on_time_orders<0 OR delayed_orders<0
 OR accepted_orders<0 OR quality_issue_orders<0 OR total_orders<>on_time_orders+delayed_orders
 OR total_orders<>accepted_orders+quality_issue_orders OR average_delivery_days<=0 OR average_price_index<=0''',
 'budget_ledger_totals': '''SELECT COUNT(*) n FROM department_budgets b LEFT JOIN
 (SELECT department_id,fiscal_year,SUM(CASE WHEN transaction_type='COMMIT' THEN amount ELSE 0 END) used,
 SUM(CASE WHEN transaction_type='RESERVE' THEN amount WHEN transaction_type IN ('RELEASE','COMMIT') THEN -amount ELSE 0 END) reserved
 FROM budget_transactions GROUP BY department_id,fiscal_year) t ON t.department_id=b.department_id AND t.fiscal_year=b.fiscal_year
 WHERE b.used_budget<>COALESCE(t.used,0) OR b.reserved_budget<>COALESCE(t.reserved,0)
 OR b.total_budget<b.used_budget+b.reserved_budget OR b.used_budget<0 OR b.reserved_budget<0''',
 'budget_running_balances': '''SELECT COUNT(*) n FROM (
 SELECT t.balance_after,b.total_budget-
 SUM(CASE WHEN t.transaction_type='ADJUST' THEN t.amount ELSE 0 END) OVER(PARTITION BY t.department_id,t.fiscal_year)
 + SUM(CASE WHEN t.transaction_type='RESERVE' THEN -t.amount WHEN t.transaction_type IN ('RELEASE','ADJUST') THEN t.amount ELSE 0 END)
 OVER(PARTITION BY t.department_id,t.fiscal_year ORDER BY t.id ROWS UNBOUNDED PRECEDING) expected
 FROM budget_transactions t JOIN department_budgets b ON b.department_id=t.department_id AND b.fiscal_year=t.fiscal_year
 ) x WHERE balance_after<>expected OR expected<0''',
 'request_reservations': '''SELECT COUNT(*) n FROM purchase_requests r LEFT JOIN purchase_orders p ON p.request_id=r.id
 LEFT JOIN (SELECT request_id,SUM(CASE WHEN transaction_type='RESERVE' THEN amount WHEN transaction_type IN ('RELEASE','COMMIT') THEN -amount ELSE 0 END) held
 FROM budget_transactions WHERE request_id IS NOT NULL GROUP BY request_id) t ON t.request_id=r.id
 WHERE COALESCE(t.held,0)<>CASE WHEN p.status='CREATED' THEN p.total_amount
 WHEN r.status IN ('PENDING_APPROVAL','APPROVED') THEN r.expected_budget ELSE 0 END''',
 'commit_order_consistency': '''SELECT COUNT(*) n FROM purchase_requests r LEFT JOIN purchase_orders p ON p.request_id=r.id
 LEFT JOIN (SELECT request_id,SUM(amount) used FROM budget_transactions WHERE transaction_type='COMMIT' GROUP BY request_id) t ON t.request_id=r.id
 WHERE COALESCE(t.used,0)<>CASE WHEN p.status='CONFIRMED' THEN p.total_amount ELSE 0 END''',
 'requester_department': '''SELECT COUNT(*) n FROM purchase_requests r JOIN employees e ON e.id=r.requester_id WHERE e.department_id<>r.department_id''',
 'order_request_state': '''SELECT COUNT(*) n FROM purchase_orders p JOIN purchase_requests r ON r.id=p.request_id
 WHERE p.department_id<>r.department_id OR p.total_amount>r.expected_budget OR
 (p.status='CANCELLED' AND r.status<>'CANCELLED') OR (p.status<>'CANCELLED' AND r.status<>'ORDER_CREATED')''',
 'order_item_request_match': '''SELECT COUNT(*) n FROM purchase_order_items i JOIN purchase_orders p ON p.id=i.purchase_order_id
 LEFT JOIN purchase_request_items r ON r.request_id=p.request_id AND r.product_id=i.product_id
 WHERE r.id IS NULL OR i.quantity<>r.quantity OR i.unit_price>r.max_unit_price''',
 'order_missing_request_items': '''SELECT COUNT(*) n FROM purchase_orders p JOIN purchase_request_items r ON r.request_id=p.request_id
 LEFT JOIN purchase_order_items i ON i.purchase_order_id=p.id AND i.product_id=r.product_id WHERE i.id IS NULL''',
 'order_quote_match': '''SELECT COUNT(*) n FROM purchase_order_items i JOIN purchase_orders p ON p.id=i.purchase_order_id
 JOIN supplier_quotes q ON q.id=i.quote_id WHERE q.supplier_id<>p.supplier_id OR q.product_id<>i.product_id OR q.unit_price<>i.unit_price''',
 'transaction_department': '''SELECT COUNT(*) n FROM budget_transactions t JOIN purchase_requests r ON r.id=t.request_id
 WHERE t.department_id<>r.department_id OR t.fiscal_year<>r.fiscal_year''',
 'duplicate_request_po': '''SELECT COUNT(*) n FROM (SELECT request_id FROM purchase_orders GROUP BY request_id HAVING COUNT(*)>1) x''',
 'duplicate_request_number': '''SELECT COUNT(*) n FROM (SELECT request_no FROM purchase_requests GROUP BY request_no HAVING COUNT(*)>1) x''',
 'duplicate_po_number': '''SELECT COUNT(*) n FROM (SELECT po_no FROM purchase_orders GROUP BY po_no HAVING COUNT(*)>1) x''',
 'invalid_quote_amount_or_delivery': '''SELECT COUNT(*) n FROM supplier_quotes WHERE unit_price<=0 OR available_quantity<0 OR delivery_days NOT BETWEEN 1 AND 365 OR valid_until<valid_from''',
 'invalid_request_amounts': '''SELECT COUNT(*) n FROM purchase_requests WHERE expected_budget<=0''',
 'invalid_order_amounts': '''SELECT COUNT(*) n FROM purchase_orders WHERE total_amount<=0''',
 'invalid_request_item_amounts': '''SELECT COUNT(*) n FROM purchase_request_items WHERE quantity<=0 OR max_unit_price<=0 OR max_total_price<>quantity*max_unit_price''',
 'invalid_order_item_amounts': '''SELECT COUNT(*) n FROM purchase_order_items WHERE quantity<=0 OR unit_price<=0 OR total_price<>quantity*unit_price''',
 'invalid_reference_price': '''SELECT COUNT(*) n FROM products WHERE reference_price<=0''',
 'invalid_transactions': '''SELECT COUNT(*) n FROM budget_transactions WHERE balance_after<0 OR (transaction_type<>'ADJUST' AND amount<=0) OR (transaction_type='ADJUST' AND amount=0)''',
 'invalid_supplier_rates': '''SELECT COUNT(*) n FROM suppliers WHERE rating NOT BETWEEN 0 AND 5 OR on_time_rate NOT BETWEEN 0 AND 1 OR quality_rate NOT BETWEEN 0 AND 1''',
 'invalid_qualifications': '''SELECT COUNT(*) n FROM supplier_qualifications WHERE valid_until<valid_from''',
 'invalid_approval_timestamp': '''SELECT COUNT(*) n FROM approval_records WHERE approval_level<=0 OR (decision='PENDING' AND decided_at IS NOT NULL) OR (decision<>'PENDING' AND decided_at IS NULL)''',
}


def audit(db=database, as_of=None, report_dir=ROOT/'reports', manifest_path=get_settings().generated_dir/'manifest.json'):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path and manifest_path.exists() else None
    as_of = as_of or date.fromisoformat(manifest['as_of']) if manifest else as_of or date.today()
    report = dict(as_of=as_of.isoformat(),database=db.settings.db_name,checks={},counts={},orphan_checks={},distributions={})
    with db.transaction() as conn:
        report['mysql_version'] = one(conn,'SELECT VERSION() version')['version']
        for table in TABLES:
            report['counts'][table] = one(conn,'SELECT COUNT(*) n FROM `'+table+'`')['n']
        report['total_rows'] = sum(report['counts'].values())
        for name,query in CHECKS.items():
            report['checks'][name] = one(conn,query)['n']
        # Discover composite foreign keys from information_schema; identifiers must match live allowlists.
        keys = all_rows(conn,'''SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME,CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION''')
        groups = {}
        for key in keys:
            assert key['TABLE_NAME'] in TABLES and key['REFERENCED_TABLE_NAME'] in TABLES
            groups.setdefault((key['TABLE_NAME'],key['CONSTRAINT_NAME']),[]).append(key)
        for (child,constraint),parts in groups.items():
            parent = parts[0]['REFERENCED_TABLE_NAME']
            on = ' AND '.join('c.`'+p['COLUMN_NAME']+'`=p.`'+p['REFERENCED_COLUMN_NAME']+'`' for p in parts)
            nonnull = ' AND '.join('c.`'+p['COLUMN_NAME']+'` IS NOT NULL' for p in parts)
            query = 'SELECT COUNT(*) n FROM `'+child+'` c LEFT JOIN `'+parent+'` p ON '+on+' WHERE '+nonnull+' AND p.id IS NULL'
            report['orphan_checks'][child+'.'+constraint] = one(conn,query)['n']
        for table in ('suppliers','supplier_qualifications','purchase_requests','purchase_orders'):
            report['distributions'][table] = all_rows(conn,'SELECT status,COUNT(*) n FROM `'+table+'` GROUP BY status ORDER BY status')
        report['distributions']['quotes'] = all_rows(conn,"""SELECT CASE WHEN valid_until<%s THEN 'EXPIRED'
            WHEN valid_from>%s THEN 'FUTURE' WHEN status='ACTIVE' THEN 'VALID' ELSE 'INACTIVE' END validity,COUNT(*) n
            FROM supplier_quotes GROUP BY validity ORDER BY validity""",(as_of,as_of))
        report['distributions']['quote_edge_cases'] = one(conn,'''SELECT SUM(available_quantity<5) low_stock,
            SUM(delivery_days>30) slow_delivery FROM supplier_quotes''')
        report['distributions']['qualification_expiring'] = one(conn,"SELECT COUNT(*) n FROM supplier_qualifications WHERE status='ACTIVE' AND valid_until BETWEEN %s AND DATE_ADD(%s,INTERVAL 30 DAY)",(as_of,as_of))['n']
        report['profiles'] = all_rows(conn,'''SELECT s.profile,AVG(q.unit_price/p.reference_price) price_index,AVG(q.delivery_days) delivery_days,
            AVG(CASE WHEN q.delivery_days<=30 THEN q.delivery_days END) normal_quote_delivery_days,
            AVG(s.on_time_rate) on_time_rate,AVG(s.quality_rate) quality_rate FROM supplier_quotes q JOIN suppliers s ON s.id=q.supplier_id
            JOIN products p ON p.id=q.product_id GROUP BY s.profile ORDER BY s.profile''')
        report['performance_profiles'] = all_rows(conn,'''SELECT s.profile,
            SUM(p.on_time_orders)/SUM(p.total_orders) observed_on_time_rate,
            SUM(p.accepted_orders)/SUM(p.total_orders) observed_quality_rate,
            AVG(p.average_delivery_days) observed_delivery_days,AVG(p.average_price_index) observed_price_index
            FROM supplier_performance p JOIN suppliers s ON s.id=p.supplier_id GROUP BY s.profile ORDER BY s.profile''')
        profiles = {p['profile']:p for p in report['profiles']}
        report['checks']['profile_correlation'] = int(not (profiles['A']['price_index']>profiles['B']['price_index']
            and profiles['A']['delivery_days']<profiles['B']['delivery_days'] and profiles['A']['quality_rate']>profiles['C']['quality_rate']))
        report['explain'] = {
            'supplier_candidates':all_rows(conn,'EXPLAIN '+CANDIDATE_QUERY,(5,1,as_of,as_of,5,'100000.00',30,as_of,as_of,as_of,as_of,100,0)),
            'department_budget':all_rows(conn,'EXPLAIN '+BUDGET_QUERY,(1,2026)),
            'purchase_order':all_rows(conn,'EXPLAIN '+ORDER_QUERY,(1,)),
        }
        report['indexes'] = {}
        for table in TABLES:
            report['indexes'][table] = all_rows(conn,'SHOW INDEX FROM `'+table+'`')
        # Require index access for the three core entry-table lookups.
        for name,alias in [('supplier_candidates','q'),('department_budget','department_budgets'),('purchase_order','purchase_orders')]:
            plans = [p for p in report['explain'][name] if p['table']==alias]
            report['checks']['index_access_'+name] = int(not plans or any(p['type']=='ALL' or not p['key'] for p in plans))
        if manifest:
            report['checks']['manifest_count_mismatches'] = sum(report['counts'][t]!=manifest['counts'][t] for t in TABLES)
            report['checks']['target_scale'] = int(not 350000<=report['total_rows']<=450000)
    report['result'] = 'PASS' if not any(report['checks'].values()) and not any(report['orphan_checks'].values()) else 'FAIL'
    report_dir.mkdir(parents=True,exist_ok=True)
    report = serialize(report)
    (report_dir/'DATASET_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 数据审计 '+report['result'],f"MySQL {report['mysql_version']} / {report['database']} / 固定数据观察日 {report['as_of']}",
             '', '| 表 | 实际行数 |','|---|---:|']
    lines += [f'| {k} | {v:,} |' for k,v in report['counts'].items()]
    lines += ['',f"总行数：{report['total_rows']:,}",'','## 关键检查（异常行数，0表示通过）','']
    lines += [f'- {k}: {v}' for k,v in report['checks'].items()]
    lines += ['',f"外键关系：{len(report['orphan_checks'])}，孤儿总数：{sum(report['orphan_checks'].values())}",
              '', '## 分布与画像','', '```json',json.dumps({'distributions':report['distributions'],'profiles':report['profiles'],'performance_profiles':report['performance_profiles']},ensure_ascii=False,indent=2),'```',
              '', '## EXPLAIN（原始结果；完整索引清单见JSON）','', '```json',json.dumps(report['explain'],ensure_ascii=False,indent=2),'```']
    (report_dir/'DATASET_AUDIT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(result=report['result'],total_rows=report['total_rows'],failed={k:v for k,v in report['checks'].items() if v}),ensure_ascii=True))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of',type=date.fromisoformat)
    report = audit(as_of=parser.parse_args().as_of)
    raise SystemExit(0 if report['result']=='PASS' else 1)
