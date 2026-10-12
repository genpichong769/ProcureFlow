"""Official mysqldump backup, protected local option file, no password in process argv."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from config import ROOT, get_settings


def backup(mysqldump):
    settings = get_settings()
    directory = settings.procureflow_data_root / 'mysql/backup'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'procureflow_before_docker_migration.sql'
    partial = target.with_suffix('.sql.partial')
    if target.exists() or partial.exists():
        raise SystemExit('Backup target exists; refusing to overwrite a prior backup.')
    config_fd, config_path = tempfile.mkstemp(prefix='.mysql-client-', suffix='.cnf', dir=directory)
    def quote(value):
        return '"' + str(value).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','\\r') + '"'
    try:
        with os.fdopen(config_fd, 'w', encoding='utf-8') as handle:
            handle.write('[client]\n' + '\n'.join(f'{k}={quote(v)}' for k,v in {
                'host':settings.db_host,'port':settings.db_port,'user':settings.db_user,
                'password':settings.db_password.get_secret_value(),'default-character-set':'utf8mb4'}.items())+'\n')
        with (directory/'mysqldump.log').open('wb') as log:
            proc = subprocess.run([str(mysqldump),'--defaults-extra-file='+config_path,
                '--single-transaction','--quick','--routines','--events','--triggers',
                '--hex-blob','--set-gtid-purged=OFF','--no-tablespaces','--column-statistics=0',
                '--databases',settings.db_name,'--result-file='+str(partial)],
                stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if proc.returncode != 0:
            raise SystemExit('mysqldump failed. Migration must not proceed; inspect the configured backup log locally.')
        if partial.stat().st_size == 0:
            raise SystemExit('Backup file is empty; migration stopped.')
        partial.rename(target)
        before = json.loads((ROOT/'reports/migration/BEFORE.json').read_text(encoding='utf-8'))
        report = dict(backup_path=str(target),bytes=target.stat().st_size,
            created_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            tool='mysqldump',result='PASS',table_count=len(before['tables']),counts=before['counts'],total_rows=before['total_rows'])
        (ROOT/'reports/migration/BACKUP.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('result','backup_path','bytes','sha256','total_rows')},ensure_ascii=True))
    finally:
        Path(config_path).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mysqldump',type=Path,required=True)
    backup(parser.parse_args().mysqldump)
