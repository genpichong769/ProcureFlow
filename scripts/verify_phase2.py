"""Freeze, capability, trace and secret checks; output findings without secret snippets."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
from config import ROOT,get_settings
from scripts.docker_mysql import inspect,verify_mounts
from scripts.verify_artifacts import verify as verify_artifacts


def verify():
    reportdir=ROOT/'reports/phase2'
    before=json.loads((reportdir/'BEFORE.json').read_text(encoding='utf-8'))
    after=json.loads((reportdir/'AFTER.json').read_text(encoding='utf-8'))
    migration=json.loads((ROOT/'reports/migration/AFTER.json').read_text(encoding='utf-8'))
    info=inspect();verify_mounts(info)
    artifacts=verify_artifacts()
    settings=get_settings()
    checks=dict(
        sixteen_tables=len(after['tables'])==16,
        total_rows_398869=after['total_rows']==398869,
        counts_unchanged=before['counts']==after['counts']==migration['counts'],
        content_hashes_unchanged=before['table_sha256']==after['table_sha256']==migration['table_sha256'],
        schema_unchanged=before['schema_sha256']==after['schema_sha256']==migration['schema_sha256'],
        same_docker_server=before['server_uuid']==after['server_uuid']==migration['server_uuid'],
        docker_endpoint=after['endpoint']=='127.0.0.1:3307' and after['datadir']=='/var/lib/mysql/',
        docker_healthy=info['state']['Health']['Status']=='healthy',
        e_drive_bind_mounts=True,
        source_original_untouched=artifacts['source_integrity']['result']=='PASS',
        original_dataset_reproducible=artifacts['reproducibility']['result']=='PASS',
        static_artifact_scan=artifacts['static_scan']['result']=='PASS',
        no_langgraph_installed=importlib.util.find_spec('langgraph') is None,
    )
    forbidden=[];classes=[]
    for folder in ('agents','a2a_server'):
        for path in (ROOT/folder).glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ClassDef) and node.name.endswith('Agent'):classes.append(node.name)
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
                    if any(n.split('.')[0] in {'db','services','mysql','langgraph'} for n in names):forbidden.append(str(path.relative_to(ROOT)))
    checks['four_agents_only']=sorted(classes)==sorted(['BudgetAgent','SupplierSourcingAgent','ComplianceApprovalAgent','ProcurementCoordinatorAgent'])
    checks['agents_no_direct_business_or_sql_imports']=not forbidden
    from agents.mcp_client import TOOLS
    checks['readonly_mcp_allowlist']=set(TOOLS)=={'budget','supplier','compliance'} and sum(map(len,TOOLS.values()))==8
    # Literal secret scans and exact in-memory comparison. Never include matched content in findings.
    values=[settings.db_password.get_secret_value()]
    key=os.getenv('DASHSCOPE_API_KEY')
    if key:values.append(key)
    values=[v for v in values if len(v)>=8]
    findings=[];files=0
    excluded={'.venv','.runtime','__pycache__','.pytest_cache'}
    candidates=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(ROOT).parts) and not p.name.startswith('.env')]
    candidates += [p for p in settings.logs_dir.rglob('*') if p.is_file()]
    for p in candidates:
        if p.suffix not in {'.py','.md','.json','.jsonl','.xml','.log','.txt','.ini','.yml','.yaml','.ps1'}:continue
        content=p.read_text(encoding='utf-8-sig',errors='replace');files+=1
        if any(v in content for v in values) or re.search(r'\bsk-[A-Za-z0-9_-]{20,}\b',content):findings.append(str(p))
    checks['no_secrets_in_code_reports_logs']=not findings
    pathrefs=[]
    for folder in ('agents','a2a_server','mcp_server'):
        for p in (ROOT/folder).glob('*.py'):
            if re.search(r'(?i)\b'+chr(80)+r':[/\\]|\bsubst\b',p.read_text(encoding='utf-8')):pathrefs.append(str(p))
    checks['no_mapped_drive_runtime_dependency']=(not pathrefs
        and settings.procureflow_data_root.resolve().drive.upper()!='P:'
        and settings.logs_dir.resolve().is_relative_to(settings.procureflow_data_root.resolve()))
    tracepath=reportdir/'evaluation-trace.jsonl'
    records=[json.loads(line) for line in tracepath.read_text(encoding='utf-8').splitlines()]
    keys={'request_id','agent_name','action','target_agent','tool_name','status','latency_ms','error_type'}
    checks['trace_required_fields']=bool(records) and all(keys<=set(r) for r in records)
    checks['trace_all_four_agents']=set(classes)<={r['agent_name'] for r in records}
    checks['trace_all_eight_mcp_tools']=set().union(*map(set,TOOLS.values()))<={r['tool_name'] for r in records if r['action']=='MCP_CALL'}
    checks['no_po_tool_called']=not any(r['tool_name']=='create_purchase_order' for r in records)
    checks['all_50_requests_completed']=len({r['request_id'] for r in records if r['action']=='REQUEST_END'})==50
    report=dict(result='PASS' if all(checks.values()) else 'FAIL',checks=checks,scan_files=files,secret_leak_paths=findings,
        forbidden_import_paths=forbidden,path_reference_findings=pathrefs,docker=info)
    (reportdir/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(result=report['result'],checks=checks),ensure_ascii=True))
    return report


if __name__=='__main__':raise SystemExit(0 if verify()['result']=='PASS' else 1)
