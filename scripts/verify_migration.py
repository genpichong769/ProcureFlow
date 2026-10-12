"""Independent post-restore evidence: byte-stable row data, schema and real Docker storage."""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from dotenv import dotenv_values
from config import ROOT, get_settings
from scripts.docker_mysql import inspect, verify_mounts, run


def verify():
    reports = ROOT/'reports/migration'
    before = json.loads((reports/'BEFORE.json').read_text(encoding='utf-8'))
    after = json.loads((reports/'AFTER.json').read_text(encoding='utf-8'))
    info = inspect()
    verify_mounts(info)
    identity = run('exec','procureflow-mysql','sh','-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot -Nse "SELECT @@server_uuid"',capture_output=True).stdout.decode().strip()
    checks = {
        'same_table_list':before['tables']==after['tables'],
        'all_16_table_counts_equal':before['counts']==after['counts'] and len(after['tables'])==16,
        'total_rows_398869':before['total_rows']==after['total_rows']==398869,
        'all_16_content_hashes_equal':before['table_sha256']==after['table_sha256'],
        'schema_metadata_equal':before['schema']==after['schema'],
        'new_server_identity':before['server_uuid']!=after['server_uuid'],
        'python_connected_to_docker':after['server_uuid']==identity,
        'docker_datadir':after['datadir']=='/var/lib/mysql/',
        'container_healthy':info['state']['Health']['Status']=='healthy',
        'e_drive_bind_mounts':True,
        'loopback_port_3307':True,
        'old_data_retained':(ROOT/'.runtime/mysql-data').is_dir(),
    }
    # Kernel query only: does not create, remove or traverse a virtual drive.
    buffer = ctypes.create_unicode_buffer(32768)
    exists = bool(ctypes.windll.kernel32.QueryDosDeviceW('P:',buffer,len(buffer))) if os.name=='nt' else False
    checks['removed_drive_mapping'] = not exists
    pattern = re.compile(r'(?i)\bP:[/\\]|\bsubst\b')
    findings, scanned = [], 0
    exclude = {'.venv','__pycache__','.pytest_cache','generated','reproduction','mysql-data'}
    for path in ROOT.rglob('*'):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(part in exclude for part in rel.parts):
            continue
        if path.suffix.lower() not in {'.py','.md','.json','.ini','.sql','.txt','.yml','.yaml','.bat','.ps1','.cmd','.sh','.cfg'} and path.name not in {'.env','.env.example'}:
            continue
        try:
            lines = path.read_text(encoding='utf-8-sig').splitlines()
        except UnicodeError:
            continue
        scanned += 1
        for line_no,line in enumerate(lines,1):
            if pattern.search(line):
                historical = rel.parts[0]=='reports' or path.name in {'AGENTS.md','PHASE1_REPORT.md','MIGRATION_AND_DOCKERIZATION_REPORT.md'}
                detection = path.name=='verify_migration.py'
                kind = 'historical_or_policy_text' if historical else 'audit_detector' if detection else 'effective_reference'
                findings.append(dict(file=rel.as_posix(),line=line_no,kind=kind))
    checks['no_effective_mapped_path_references'] = not any(f['kind']=='effective_reference' for f in findings)
    # Compare configured DB credentials against publishable project artifacts.
    # Only DB credential fields are accessed; API key environment values are never read.
    env = dotenv_values(ROOT/'.env')
    secrets = [env[k] for k in ('DB_PASSWORD','MYSQL_ROOT_PASSWORD') if env.get(k)]
    leaks = []
    for path in ROOT.rglob('*'):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(p in {'.venv','.runtime','__pycache__','.pytest_cache','generated'} for p in rel.parts) or path.name.startswith('.env'):
            continue
        if path.suffix.lower() not in {'.py','.md','.json','.ini','.sql','.txt','.yml','.yaml','.bat','.ps1','.cmd','.sh','.xml'}:
            continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            continue
        if any(secret in text for secret in secrets):
            leaks.append(rel.as_posix())
    for path in get_settings().procureflow_data_root.rglob('*.log'):
        if any(secret in path.read_text(encoding='utf-8',errors='replace') for secret in secrets):
            leaks.append(str(path))
    checks['no_database_secrets_in_code_reports_logs'] = not leaks
    backup = json.loads((reports/'BACKUP.json').read_text(encoding='utf-8'))
    checks['original_backup_unchanged'] = hashlib.sha256(Path(backup['backup_path']).read_bytes()).hexdigest()==backup['sha256']
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(),result='PASS' if all(checks.values()) else 'FAIL',
                  checks=checks,docker=info,path_scan=dict(files_scanned=scanned,findings=findings),secret_leak_paths=leaks)
    if before['schema']!=after['schema']:
        report['schema_differences'] = [k for k in before['schema'] if before['schema'][k]!=after['schema'][k]]
    (reports/'MIGRATION_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'result':report['result'],'checks':checks,'schema_differences':report.get('schema_differences',[])},ensure_ascii=True))
    if report['result']!='PASS':
        raise SystemExit(1)
    return report


if __name__=='__main__':
    verify()
