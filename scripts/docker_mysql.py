"""Manage project Compose MySQL without altering other containers or global Docker settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from config import ROOT, get_settings

CONTAINER = 'procureflow-mysql'


def run(*args, **kwargs):
    return subprocess.run(['docker', *args], cwd=ROOT, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, **kwargs)


def inspect():
    # Never display Config.Env: Docker stores resolved credentials there.
    raw = run('inspect',CONTAINER,capture_output=True).stdout
    container = json.loads(raw)[0]
    return dict(name=container['Name'].lstrip('/'),id=container['Id'],image_id=container['Image'],
        configured_image=container['Config']['Image'],state=container['State'],
        ports=container['HostConfig']['PortBindings'],mounts=container['Mounts'],
        logging_driver=container['HostConfig']['LogConfig']['Type'])


def verify_mounts(info):
    root = get_settings().procureflow_data_root.resolve()
    expected = {'/var/lib/mysql':root/'mysql/data',
                '/var/log/mysql':root/'mysql/logs',
                '/backup':root/'mysql/backup'}
    for target,source in expected.items():
        mount = next((m for m in info['mounts'] if m['Destination']==target),None)
        if mount is None or mount['Type']!='bind':
            raise RuntimeError('Required configured bind mount missing: '+target)
        actual = mount['Source'].replace('\\','/').lower().rstrip('/')
        host = str(source).replace('\\','/').lower().rstrip('/')
        accepted = {host}
        if source.drive:
            drive = source.drive[0].lower()
            tail = host[2:]
            accepted.update({f'/run/desktop/mnt/host/{drive}{tail}',f'/host_mnt/{drive}{tail}'})
        if actual not in accepted:
            raise RuntimeError('Unexpected host storage directory for '+target)
        if target=='/backup' and mount['RW']:
            raise RuntimeError('Backup bind mount must be read-only')
    if info['ports'].get('3306/tcp') != [{'HostIp':'127.0.0.1','HostPort':'3307'}]:
        raise RuntimeError('MySQL must bind only 127.0.0.1:3307')
    if info['logging_driver']!='none':
        raise RuntimeError('Container logs must not use Docker global log files')


def prepare():
    root = get_settings().procureflow_data_root
    for rel in ('mysql/data','mysql/backup','mysql/logs','generated','logs/mcp'):
        path = root/rel
        path.mkdir(parents=True,exist_ok=True)
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Persistent directory resolves outside PROCUREFLOW_DATA_ROOT')
    run('compose','config','--quiet')
    print('Compose configuration valid; persistent directories verified under PROCUREFLOW_DATA_ROOT.')


def restore(backup):
    info = inspect()
    verify_mounts(info)
    backup = backup.resolve(strict=True)
    allowed = (get_settings().procureflow_data_root/'mysql/backup').resolve()
    if backup.parent!=allowed or backup.name!='procureflow_before_docker_migration.sql':
        raise RuntimeError('Only the recorded migration backup may be restored by this command')
    evidence = json.loads((ROOT/'reports/migration/BACKUP.json').read_text(encoding='utf-8'))
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=evidence['sha256']:
        raise RuntimeError('Backup checksum mismatch; restore refused')
    empty = run('exec',CONTAINER,'sh','-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot -Nse "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\'procureflow\'"',capture_output=True)
    if empty.stdout.strip()!=b'0':
        raise RuntimeError('Restore target is not empty; refusing to replace existing schema or data')
    log = get_settings().procureflow_data_root/'mysql/backup/restore.log'
    with backup.open('rb') as source, log.open('wb') as output:
        run('exec','-i',CONTAINER,'sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=socket -uroot --default-character-set=utf8mb4',
            stdin=source,stdout=output,stderr=output)
    print('Original backup restored into Docker MySQL; verification is still required.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','start','stop','status','inspect','restore'])
    parser.add_argument('--backup',type=Path,
        default=get_settings().procureflow_data_root/'mysql/backup/procureflow_before_docker_migration.sql')
    args = parser.parse_args()
    if args.action=='prepare':
        prepare()
    elif args.action=='start':
        prepare()
        run('compose','up','-d','mysql')
    elif args.action=='stop':
        run('compose','stop','mysql')
    elif args.action=='status':
        run('compose','ps','mysql')
    elif args.action=='inspect':
        info = inspect()
        verify_mounts(info)
        print(json.dumps(info,ensure_ascii=True))
    else:
        restore(args.backup)


if __name__=='__main__':
    main()
