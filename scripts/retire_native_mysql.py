"""One-time guarded shutdown of the backed-up dedicated native instance.
Does not delete/move project data, manipulate drive mappings, or stop Windows services.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
from dotenv import dotenv_values, set_key
import mysql.connector
from config import ROOT, get_settings


def main():
    reports = ROOT/'reports/migration'
    before = json.loads((reports/'BEFORE.json').read_text(encoding='utf-8'))
    evidence = json.loads((reports/'BACKUP.json').read_text(encoding='utf-8'))
    backup = Path(evidence['backup_path'])
    if evidence['result']!='PASS' or hashlib.sha256(backup.read_bytes()).hexdigest()!=evidence['sha256']:
        raise SystemExit('Verified backup required before shutdown.')
    if before['total_rows']!=398869 or len(before['counts'])!=16:
        raise SystemExit('Unexpected original dataset; shutdown refused.')
    settings = get_settings()
    data_root = settings.procureflow_data_root
    archive = data_root/'mysql/backup/legacy-native-config'
    archive.mkdir(parents=True,exist_ok=True)
    for src in [ROOT/'.env',ROOT/'.runtime/admin.env',ROOT/'.runtime/instance.json',ROOT/'.runtime/my.ini']:
        dest = archive/('project.env' if src.name=='.env' else src.name)
        if dest.exists():
            raise SystemExit('Legacy config archive already exists; do not repeat the retirement step.')
        shutil.copy2(src,dest)
    old_reports = reports/'phase1_before'
    old_reports.mkdir(exist_ok=True)
    for filename in ('DATASET_AUDIT.json','DATASET_AUDIT.md','VERIFICATION.json','MCP_HTTP_SMOKE.json','pytest.xml','pytest_http.xml','PHASE1_RESULTS.json'):
        shutil.copy2(ROOT/'reports'/filename,old_reports/filename)
    admin_secret = dotenv_values(ROOT/'.runtime/admin.env')['MYSQL_ADMIN_PASSWORD']
    kwargs = settings.connection_kwargs()
    kwargs.update(user='root',password=admin_secret)
    conn = mysql.connector.connect(**kwargs)
    with conn.cursor(buffered=True) as cursor:
        cursor.execute('SELECT @@server_uuid,@@datadir')
        identity = cursor.fetchone()
        if identity!=(before['server_uuid'],before['datadir']):
            raise SystemExit('Connected instance identity changed; shutdown refused.')
        cursor.execute('SHOW DATABASES')
        databases = {row[0] for row in cursor.fetchall()}
        allowed = {'procureflow','procureflow_test','information_schema','mysql','performance_schema','sys'}
        if not databases<=allowed:
            raise SystemExit('Instance contains other databases; automatic shutdown refused.')
        cursor.execute('SHUTDOWN')
    conn.close()
    env_file = ROOT/'.env'
    updates = {'DB_HOST':'127.0.0.1','DB_PORT':'3307','DB_USER':'procureflow','DB_NAME':'procureflow',
               'MYSQL_ROOT_PASSWORD':secrets.token_urlsafe(32),'PROCUREFLOW_DATA_ROOT':str(data_root).replace('\\','/')}
    for key,value in updates.items():
        set_key(env_file,key,value,quote_mode='always')
    # Original files stay in place; legacy startup metadata is explicitly inert.
    (ROOT/'.runtime/my.ini').write_text('# RETIRED native instance. Preserved data must not be started from this file.\n'
                                      '# Current service is docker-compose.yml:mysql.\n',encoding='utf-8')
    (ROOT/'.runtime/instance.json').write_text(json.dumps(dict(retired=True,
        original_data_directory=str(ROOT/'.runtime/mysql-data'),archived_configuration=str(archive),
        current_service='docker-compose.yml:mysql'),ensure_ascii=False,indent=2),encoding='utf-8')
    report = dict(retired_at=datetime.now(timezone.utc).isoformat(),result='PASS',
        original_datadir_reported=before['datadir'],original_real_directory=str(ROOT/'.runtime/mysql-data'),
        on_c_drive=False,databases=sorted(databases),old_data_retained=True,
        legacy_config_archive=str(archive),windows_service_modified=False)
    (reports/'NATIVE_RETIREMENT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Dedicated native instance shut down; original data retained; project configuration switched to Docker credentials.')


if __name__=='__main__':
    main()
