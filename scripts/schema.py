"""Trusted table allowlist in foreign-key dependency order."""
from config import ROOT

TABLES = ('departments','employees','department_budgets','products','suppliers',
          'supplier_qualifications','supplier_quotes','supplier_performance','procurement_rules',
          'approval_rules','purchase_requests','purchase_request_items','approval_records',
          'purchase_orders','purchase_order_items','budget_transactions')


def initialize(conn):
    with conn.cursor() as cursor:
        cursor.execute('SHOW TABLES')
        existing = {row[0] for row in cursor.fetchall()}
        if existing:
            if existing != set(TABLES):
                raise RuntimeError('Database is not an empty schema or a complete ProcureFlow schema; refusing changes.')
            return
        for filename in ('create_tables.sql','create_indexes.sql'):
            sql = (ROOT / 'sql' / filename).read_text(encoding='utf-8')
            sql = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
            for statement in sql.split(';'):
                if statement.strip():
                    cursor.execute(statement)
    conn.commit()
