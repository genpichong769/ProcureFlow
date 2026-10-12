"""Metadata-only workflow trace. It never records prompts, credentials or exception text."""
from datetime import datetime,timezone
import json
from time import perf_counter
from config import get_settings


def workflow_trace(workflow_id,node_name,event,request_id=None,checkpoint_status=None,
                   approval_level=None,decision=None,po_no=None,duration_ms=0,error_type=None):
    settings=get_settings()
    path=settings.require_persistent_path(settings.logs_dir/'workflow/trace.jsonl')
    path.parent.mkdir(parents=True,exist_ok=True)
    record=dict(timestamp=datetime.now(timezone.utc).isoformat(),workflow_id=workflow_id,request_id=request_id,
        node_name=node_name,event=event,checkpoint_status=checkpoint_status,approval_level=approval_level,
        decision=decision,po_no=po_no,duration_ms=round(duration_ms,3),error_type=error_type)
    with path.open('a',encoding='utf-8') as handle:
        handle.write(json.dumps(record,ensure_ascii=False)+'\n')


def elapsed(start):
    return (perf_counter()-start)*1000
