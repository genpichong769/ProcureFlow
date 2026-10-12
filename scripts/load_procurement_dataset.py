"""Safe bulk load: refuse populated schemas, validate file hashes, atomic DML import."""
import argparse
import hashlib
import json
from pathlib import Path
import mysql.connector
from config import ROOT, get_settings
from scripts.schema import TABLES, initialize


def load(folder, settings=None):
    settings = settings or get_settings()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    for table in TABLES:
        name = table+'.jsonl'
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != manifest['files'][name]:
            raise RuntimeError('Dataset hash mismatch: '+table)
    conn = mysql.connector.connect(**settings.connection_kwargs())
    try:
        initialize(conn)
        with conn.cursor(buffered=True) as cursor:
            for table in TABLES:
                cursor.execute('SELECT COUNT(*) FROM `'+table+'`')  # trusted allowlist
                if cursor.fetchone()[0]:
                    raise RuntimeError('Refusing to load into a populated database: '+table)
        conn.commit()
        conn.start_transaction()
        with conn.cursor(buffered=True) as cursor:
            for table in TABLES:
                cursor.execute('SELECT * FROM `'+table+'` LIMIT 0')
                columns = cursor.column_names
                statement = 'INSERT INTO `'+table+'` ('+','.join('`'+c+'`' for c in columns)+') VALUES ('+','.join(['%s']*len(columns))+')'
                batch, count = [], 0
                with (folder/(table+'.jsonl')).open(encoding='utf-8') as handle:
                    for line in handle:
                        record = json.loads(line)
                        if set(record) != set(columns):
                            raise RuntimeError('Dataset column mismatch: '+table)
                        batch.append(tuple(record[c] for c in columns))
                        count += 1
                        if len(batch) == 1000:
                            cursor.executemany(statement,batch)
                            batch.clear()
                    if batch:
                        cursor.executemany(statement,batch)
                if count != manifest['counts'][table]:
                    raise RuntimeError('Dataset row count mismatch: '+table)
                print(table,count,flush=True)
        conn.commit()
        print('Dataset import committed.')
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,default=get_settings().generated_dir)
    load(parser.parse_args().input)
