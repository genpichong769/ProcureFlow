"""Safe errors and metadata-only trace. No raw prompts, credentials or exception messages."""
import json
import os
import hashlib
from datetime import datetime, timezone
from time import perf_counter
from config import get_settings


class AgentFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def trace(request_id, agent_name, action, target_agent=None, tool_name=None,
          status='SUCCESS', latency_ms=0, error_type=None):
    settings = get_settings()
    path = settings.require_persistent_path(settings.logs_dir/'agents/trace.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(timestamp=datetime.now(timezone.utc).isoformat(),request_id=request_id,
        agent_name=agent_name,action=action,target_agent=target_agent,tool_name=tool_name,
        status=status,latency_ms=round(latency_ms,3),error_type=error_type)
    payload = (json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
    _append_locked(path, payload)


def _append_locked(path, payload):
    """Serialize appends across A2A/MCP processes on Windows and POSIX."""
    if os.name == 'nt':
        import ctypes
        name = 'Local\\ProcureFlowTrace_' + hashlib.sha256(str(path.resolve()).encode('utf-8')).hexdigest()
        kernel = ctypes.windll.kernel32
        handle = kernel.CreateMutexW(None, False, name)
        if not handle:
            raise OSError('TRACE_MUTEX_CREATE_FAILED')
        acquired = kernel.WaitForSingleObject(handle, 10000)
        if acquired not in (0, 0x80):
            kernel.CloseHandle(handle)
            raise TimeoutError('TRACE_LOCK_TIMEOUT')
        try:
            descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            try:
                os.write(descriptor, payload)
            finally:
                os.close(descriptor)
        finally:
            kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    else:
        lock_path = path.with_suffix(path.suffix + '.lock')
        with lock_path.open('a+b', buffering=0) as lock:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
                try:
                    os.write(descriptor, payload)
                finally:
                    os.close(descriptor)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def milliseconds(start):
    return (perf_counter()-start)*1000
