"""Exact, prefix-scoped cleanup for Phase3 integration writes. Never touches non-P3TEST requests."""
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import mysql.connector
from config import ROOT,get_settings

TABLES=('purchase_requests','purchase_request_items','approval_records','purchase_orders','purchase_order_items','budget_transactions')
BASELINE=ROOT/'reports/phase3/CLEANUP_BASELINE.json'


def encode(value):
    if isinstance(value,Decimal):return str(value)
    if hasattr(value,'isoformat'):return value.isoformat()
    raise TypeError(type(value).__name__)


def capture():
    settings=get_settings();conn=mysql.connector.connect(**settings.connection_kwargs())
    try:
        with conn.cursor(dictionary=True,buffered=True) as cur:
            cur.execute("SELECT COUNT(*) n FROM purchase_requests WHERE request_no LIKE 'P3TEST-%'")
            if cur.fetchone()['n']:raise RuntimeError('P3TEST rows already exist; clean them before replacing cleanup baseline')
            cur.execute('SELECT id,used_budget,reserved_budget,updated_at FROM department_budgets')
            budgets=cur.fetchall()
            cur.execute('''SELECT TABLE_NAME,AUTO_INCREMENT FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('''+','.join(['%s']*len(TABLES))+')',TABLES)
            auto={r['TABLE_NAME']:r['AUTO_INCREMENT'] for r in cur.fetchall()}
        report=dict(captured_at=datetime.now().isoformat(),budgets=budgets,auto_increment=auto)
        BASELINE.parent.mkdir(parents=True,exist_ok=True)
        BASELINE.write_text(json.dumps(report,default=encode,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(result='PASS',budgets=len(budgets),auto_increment=auto)))
        return report
    finally:conn.close()


def cleanup():
    if not BASELINE.exists():raise RuntimeError('Capture cleanup baseline before running Phase3 writes')
    baseline=json.loads(BASELINE.read_text(encoding='utf-8'));budget={r['id']:r for r in baseline['budgets']}
    settings=get_settings();conn=mysql.connector.connect(**settings.connection_kwargs())
    removed=0
    try:
        conn.start_transaction(isolation_level='SERIALIZABLE')
        with conn.cursor(dictionary=True,buffered=True) as cur:
            cur.execute("SELECT id,request_no FROM purchase_requests WHERE request_no LIKE 'P3TEST-%' FOR UPDATE")
            requests=cur.fetchall();ids=[r['id'] for r in requests]
            if any(not r['request_no'].startswith('P3TEST-') for r in requests):raise RuntimeError('Cleanup scope violation')
            if ids:
                marks=','.join(['%s']*len(ids))
                cur.execute('''SELECT oi.quote_id,SUM(oi.quantity) quantity FROM purchase_order_items oi
                    JOIN purchase_orders po ON po.id=oi.purchase_order_id WHERE po.request_id IN ('''+marks+') GROUP BY oi.quote_id',ids)
                for row in cur.fetchall():
                    if row['quote_id'] is not None:cur.execute('UPDATE supplier_quotes SET available_quantity=available_quantity+%s WHERE id=%s',(row['quantity'],row['quote_id']))
                cur.execute('''SELECT b.id,SUM(CASE WHEN t.transaction_type='COMMIT' THEN t.amount ELSE 0 END) committed,
                    SUM(CASE WHEN t.transaction_type='RESERVE' THEN t.amount WHEN t.transaction_type IN ('RELEASE','COMMIT') THEN -t.amount ELSE 0 END) net_reserved
                    FROM budget_transactions t JOIN department_budgets b ON b.department_id=t.department_id AND b.fiscal_year=t.fiscal_year
                    WHERE t.request_id IN ('''+marks+') GROUP BY b.id',ids)
                for row in cur.fetchall():
                    original=budget[str(row['id'])] if str(row['id']) in budget else budget[row['id']]
                    cur.execute('UPDATE department_budgets SET used_budget=used_budget-%s,reserved_budget=reserved_budget-%s,updated_at=%s WHERE id=%s',
                        (row['committed'],row['net_reserved'],original['updated_at'],row['id']))
                for sql in (
                    'DELETE oi FROM purchase_order_items oi JOIN purchase_orders po ON po.id=oi.purchase_order_id WHERE po.request_id IN ('+marks+')',
                    'DELETE FROM purchase_orders WHERE request_id IN ('+marks+')',
                    'DELETE FROM approval_records WHERE request_id IN ('+marks+')',
                    'DELETE FROM budget_transactions WHERE request_id IN ('+marks+')',
                    'DELETE FROM purchase_request_items WHERE request_id IN ('+marks+')',
                    'DELETE FROM purchase_requests WHERE id IN ('+marks+')'):
                    cur.execute(sql,ids);removed+=cur.rowcount
        conn.commit()
        with conn.cursor() as cur:
            for table in TABLES:
                value=baseline['auto_increment'].get(table)
                if value is not None:cur.execute(f'ALTER TABLE `{table}` AUTO_INCREMENT = {int(value)}')
        conn.commit()
        print(json.dumps(dict(result='PASS',requests=len(ids),rows_removed=removed)))
        return dict(requests=len(ids),rows_removed=removed)
    except BaseException:conn.rollback();raise
    finally:conn.close()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','cleanup']);args=parser.parse_args()
    capture() if args.action=='capture' else cleanup()
