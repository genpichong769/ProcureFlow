"""Record source integrity, deterministic reproduction and static secret/API checks.
Never read .env, process API keys, or print candidate secret values.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
from config import ROOT, get_settings


def verify():
    baseline = json.loads((ROOT/'reports/source_baseline.json').read_text(encoding='utf-8-sig'))
    changed = [r['path'] for r in baseline if not Path(r['path']).exists() or hashlib.sha256(Path(r['path']).read_bytes()).hexdigest().upper()!=r['sha256']]
    actual_paths = {str(p) for p in (ROOT.parent/'SmartVoyage').rglob('*') if p.is_file()}
    recorded = {r['path'] for r in baseline if not r['path'].endswith('.zip')}
    source_result = dict(result='PASS' if not changed and actual_paths==recorded else 'FAIL',
                         files_checked=len(baseline),changed_paths=changed,added_paths=sorted(actual_paths-recorded))
    inventory = []
    for path in sorted((ROOT.parent/'SmartVoyage').rglob('*')):
        if path.suffix not in ('.py','.sql','.txt'):
            continue
        text = path.read_text(encoding='utf-8-sig')
        info = dict(path=path.relative_to(ROOT.parent/'SmartVoyage').as_posix(),lines=len(text.splitlines()))
        if path.suffix=='.py':
            tree = ast.parse(text)
            info['functions'] = [n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
            info['classes'] = [n.name for n in ast.walk(tree) if isinstance(n,ast.ClassDef)]
            info['imports'] = sorted({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module})
        inventory.append(info)
    data_root = get_settings().procureflow_data_root
    manifest = json.loads((data_root/'generated/manifest.json').read_text(encoding='utf-8'))
    reproduced = json.loads((data_root/'generated/reproduction/manifest.json').read_text(encoding='utf-8'))
    reproduction = dict(result='PASS' if manifest==reproduced else 'FAIL',seed=manifest['seed'],
        compared_files=len(manifest['files']),total_rows=manifest['total_rows'],file_hashes=manifest['files'])
    findings, scanned = [], 0
    excluded = {'.venv','.runtime','__pycache__','.pytest_cache','generated','logs'}
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(p in excluded for p in path.relative_to(ROOT).parts) or path.name in ('.env','.env.example'):
            continue
        if path.suffix not in ('.py','.sql','.md','.txt','.json','.ini','.yml','.yaml','.sh','.ps1','.bat','.cmd'):
            continue
        scanned += 1
        content = path.read_text(encoding='utf-8-sig')
        # Structured reports contain file paths / rule names but no source secret snippets.
        if re.search(r'\bsk-[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',content):
            findings.append({'path':path.relative_to(ROOT).as_posix(),'kind':'key-shaped literal'})
        if path.suffix in ('.yml','.yaml'):
            for line_no,line in enumerate(content.splitlines(),1):
                match = re.match(r'\s*(?:MYSQL_ROOT_PASSWORD|MYSQL_PASSWORD|DB_PASSWORD)\s*:\s*(.*)',line)
                if match and not match.group(1).strip(' \'"').startswith('${'):
                    findings.append({'path':path.relative_to(ROOT).as_posix(),'line':line_no,'kind':'literal password in compose'})
        if path.suffix=='.py':
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str) and node.value.value:
                    for target in node.targets:
                        if isinstance(target,ast.Name) and re.search(r'(password|api_key|secret|token)$',target.id,re.I):
                            findings.append({'path':path.relative_to(ROOT).as_posix(),'line':node.lineno,'kind':'secret-named string assignment'})
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    modules = [n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or '']
                    if any(m.split('.')[0] in ('streamlit',) for m in modules):
                        findings.append({'path':path.relative_to(ROOT).as_posix(),'line':node.lineno,'kind':'out-of-phase import'})
    report = dict(source_integrity=source_result,reproducibility=reproduction,
                  static_scan=dict(result='PASS' if not findings else 'FAIL',files_scanned=scanned,findings=findings,
                                   scope='Project text files excluding .env, examples, runtime, dependencies, generated rows and logs; no environment secret values read'),
                  source_inventory=inventory)
    (ROOT/'reports/VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key]['result'] for key in ('source_integrity','reproducibility','static_scan')}))
    return report


if __name__ == '__main__':
    result = verify()
    raise SystemExit(0 if all(result[k]['result']=='PASS' for k in ('source_integrity','reproducibility','static_scan')) else 1)
