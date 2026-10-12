"""Read-only database evidence: exact counts, content hashes and schema metadata.
This script never reads or serializes an API key or connection password.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import mysql.connector
from config import ROOT, get_settings
from scripts.schema import TABLES


def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(type(value).__name__)


def canonical(value):
    return json.dumps(value, default=encode, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def snapshot(output):
    settings = get_settings()
    conn = mysql.connector.connect(**settings.connection_kwargs())
    report = dict(captured_at=datetime.now(timezone.utc).isoformat(), database=settings.db_name,
                  endpoint=f'{settings.db_host}:{settings.db_port}', counts={}, table_sha256={})
    try:
        conn.start_transaction(isolation_level='REPEATABLE READ', consistent_snapshot=True, readonly=True)
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            cursor.execute('SHOW VARIABLES LIKE %s', ('datadir',))
            report['datadir_query'] = "SHOW VARIABLES LIKE 'datadir';"
            report['datadir'] = cursor.fetchone()['Value']
            cursor.execute('SELECT VERSION() version, @@hostname hostname, @@port port, @@server_uuid server_uuid')
            report.update(cursor.fetchone())
            cursor.execute('SHOW TABLES')
            actual = sorted(next(iter(r.values())) for r in cursor.fetchall())
            if set(actual) != set(TABLES):
                raise RuntimeError('Unexpected table list; migration stopped.')
            report['tables'] = actual
            cursor.execute('SHOW DATABASES')
            report['visible_databases'] = [next(iter(r.values())) for r in cursor.fetchall()]
        for table in TABLES:
            digest = hashlib.sha256()
            count = 0
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute('SELECT * FROM `' + table + '` ORDER BY id')
                while batch := cursor.fetchmany(2000):
                    for row in batch:
                        digest.update((canonical(row) + '\n').encode('utf-8'))
                        count += 1
            report['counts'][table] = count
            report['table_sha256'][table] = digest.hexdigest()
        schema_queries = {
            'columns': '''SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,COLLATION_NAME
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION''',
            'indexes': '''SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE
                FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX''',
            'foreign_keys': '''SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,ORDINAL_POSITION,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
                ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION''',
            'checks': '''SELECT CONSTRAINT_NAME,CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA=DATABASE() ORDER BY CONSTRAINT_NAME''',
            'table_options': '''SELECT TABLE_NAME,ENGINE,TABLE_COLLATION,AUTO_INCREMENT FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME''',
        }
        report['schema'] = {}
        with conn.cursor(dictionary=True, buffered=True) as cursor:
            for kind, sql in schema_queries.items():
                cursor.execute(sql)
                report['schema'][kind] = cursor.fetchall()
        report['total_rows'] = sum(report['counts'].values())
        report['schema_sha256'] = hashlib.sha256(canonical(report['schema']).encode('utf-8')).hexdigest()
        conn.commit()
    finally:
        conn.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, default=encode, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('version','datadir','endpoint','total_rows','counts')}, ensure_ascii=True))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    snapshot(parser.parse_args().output)
