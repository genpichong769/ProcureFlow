"""Final Phase3 verification after all P3TEST business rows have been cleaned."""
import ast,hashlib,importlib.metadata as metadata,json,os,re
from pathlib import Path
import mysql.connector
from config import ROOT,get_settings
from scripts.docker_mysql import inspect,verify_mounts
from scripts.verify_artifacts import verify as verify_artifacts


def verify():
    folder=ROOT/'reports/phase3'
    before=json.loads((folder/'BEFORE.json').read_text(encoding='utf-8'))
    after=json.loads((folder/'AFTER.json').read_text(encoding='utf-8'))
    evaluation=json.loads((folder/'evaluation.json').read_text(encoding='utf-8'))
    restart=json.loads((folder/'restart-resume.json').read_text(encoding='utf-8'))
    info=inspect();verify_mounts(info);settings=get_settings();artifacts=verify_artifacts()
    checkpoint=settings.require_persistent_path(settings.checkpoint_path)
    conn=mysql.connector.connect(**settings.connection_kwargs())
    try:
        with conn.cursor(dictionary=True,buffered=True) as cur:
            cur.execute("SELECT COUNT(*) n FROM purchase_requests WHERE request_no LIKE 'P3TEST-%'");test_rows=cur.fetchone()['n']
            cur.execute("SELECT COUNT(*) n FROM purchase_orders po JOIN purchase_requests pr ON pr.id=po.request_id WHERE pr.request_no LIKE 'P3TEST-%'");test_orders=cur.fetchone()['n']
    finally:conn.close()
    checks=dict(
        phase3_evaluation=evaluation['result']=='PASS' and evaluation['scenario_count']==30,
        sixteen_tables=len(after['tables'])==16,
        cleanup_rows_398869=after['total_rows']==before['total_rows']==398869,
        cleanup_counts_equal=after['counts']==before['counts'],
        cleanup_content_hashes_equal=after['table_sha256']==before['table_sha256'],
        cleanup_schema_equal=after['schema_sha256']==before['schema_sha256'],
        no_p3test_requests=test_rows==0 and test_orders==0,
        same_docker_server=after['server_uuid']==before['server_uuid'],
        docker_healthy=info['state']['Health']['Status']=='healthy',
        configured_mysql_bind=True,
        checkpoint_exists=checkpoint.exists() and checkpoint.stat().st_size>0,
        checkpoint_under_configured_root=checkpoint.resolve().is_relative_to(
            settings.procureflow_data_root.resolve()),
        restart_resume_real=restart['result']=='PASS' and restart['different_process'] and restart['start_pid']!=restart['resume_pid'],
        source_original_untouched=artifacts['source_integrity']['result']=='PASS',
        original_dataset_reproducible=artifacts['reproducibility']['result']=='PASS',
        static_artifact_scan=artifacts['static_scan']['result']=='PASS',
        dependency_versions=(metadata.version('langgraph')=='0.6.11' and metadata.version('langgraph-checkpoint-sqlite')=='2.0.11'),
    )
    classes=[];runtime_forbidden=[]
    for foldername in ('agents','a2a_server'):
        for path in (ROOT/foldername).glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            classes += [n.name for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name.endswith('Agent')]
    checks['four_agents_only']=sorted(classes)==sorted(['BudgetAgent','SupplierSourcingAgent','ComplianceApprovalAgent','ProcurementCoordinatorAgent'])
    for path in (ROOT/'workflow').glob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                names=[x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or '']
                if any(x.split('.')[0] in {'db','services','mysql'} for x in names):runtime_forbidden.append(str(path.relative_to(ROOT)))
    checks['workflow_no_direct_business_or_db_imports']=not runtime_forbidden
    runtime_python=[p for directory in ('workflow','agents','a2a_server','api','services') for p in (ROOT/directory).glob('*.py')]
    checks['single_langgraph_owner']=sum('StateGraph(' in p.read_text(encoding='utf-8') for p in runtime_python)==1
    tracepath=settings.logs_dir/'workflow/trace.jsonl';traces=[json.loads(x) for x in tracepath.read_text(encoding='utf-8').splitlines() if x.strip()]
    required={'workflow_id','request_id','node_name','event','checkpoint_status','approval_level','decision','po_no','duration_ms','error_type'}
    checks['workflow_trace_fields']=bool(traces) and all(required<=set(t) for t in traces)
    checks['workflow_trace_interrupt_resume']=any(t['event']=='INTERRUPT' for t in traces) and any(t['event']=='RESUME' for t in traces)
    values=[settings.db_password.get_secret_value(),os.getenv('DASHSCOPE_API_KEY','')];values=[x for x in values if len(x)>=8]
    findings=[];scanned=0;excluded={'.venv','.runtime','__pycache__','.pytest_cache'}
    paths=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(ROOT).parts) and not p.name.startswith('.env')]
    paths += [p for p in settings.logs_dir.rglob('*') if p.is_file()]
    for path in paths:
        if path.suffix not in {'.py','.md','.json','.jsonl','.xml','.log','.txt','.ini','.yml','.yaml'}:continue
        content=path.read_text(encoding='utf-8-sig',errors='replace');scanned+=1
        if any(value in content for value in values) or re.search(r'\bsk-[A-Za-z0-9_-]{20,}\b',content):findings.append(str(path))
    checks['no_secrets_in_code_reports_logs']=not findings
    mapped=[]
    for path in [*ROOT.joinpath('agents').glob('*.py'),*ROOT.joinpath('workflow').glob('*.py'),*ROOT.joinpath('api').glob('*.py')]:
        if re.search(r'(?i)\b'+chr(80)+r':[/\\]|\bsubst\b',path.read_text(encoding='utf-8')):mapped.append(str(path))
    checks['no_mapped_drive_runtime_dependency']=not mapped
    checks['no_unrelated_infrastructure']=not any((ROOT/name).exists() for name in ('redis','kafka','milvus','celery','minio','rag'))
    result=dict(result='PASS' if all(checks.values()) else 'FAIL',checks=checks,secret_scan_files=scanned,
        secret_findings=findings,runtime_forbidden_imports=runtime_forbidden,mapped_path_findings=mapped,
        checkpoint=dict(path=str(checkpoint),bytes=checkpoint.stat().st_size if checkpoint.exists() else 0),docker=info)
    (ROOT/'reports/phase3/verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(result=result['result'],checks=checks),ensure_ascii=True))
    return result


if __name__=='__main__':raise SystemExit(0 if verify()['result']=='PASS' else 1)
