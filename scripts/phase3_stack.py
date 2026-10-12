"""Own the eight Phase3 business processes; reuse only the existing Docker MySQL."""
from contextlib import contextmanager
import os,socket,subprocess,sys,time
from config import ROOT,get_settings


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.3);return sock.connect_ex((get_settings().agent_host,port))==0


@contextmanager
def stack(include_api=False):
    s=get_settings()
    modules=[(f'mcp_server.mcp_{r}_server',getattr(s,f'mcp_{r}_port')) for r in ('budget','supplier','compliance','procurement')]
    modules += [(f'a2a_server.{r}_agent_server',getattr(s,f'a2a_{r}_port')) for r in ('budget','supplier','compliance','procurement')]
    if include_api:modules.append(('api',s.workflow_api_port))
    if any(listening(port) for _,port in modules):raise RuntimeError('Phase3 ports occupied')
    logdir=s.require_persistent_path(s.logs_dir/'phase3-services');logdir.mkdir(parents=True,exist_ok=True)
    children=[]
    try:
        for module,port in modules:
            handle=(logdir/(module+'.log')).open('w',encoding='utf-8')
            cmd=[sys.executable,'-m',module] if module!='api' else [sys.executable,'-m','uvicorn','api.workflow_api:app','--host',s.agent_host,'--port',str(port)]
            proc=subprocess.Popen(cmd,cwd=ROOT,stdout=handle,stderr=handle,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append((proc,handle,port))
        deadline=time.monotonic()+60
        while not all(listening(p) for _,_,p in children):
            if any(p.poll() is not None for p,_,_ in children) or time.monotonic()>deadline:raise RuntimeError('Phase3 service startup failed; inspect logs under PROCUREFLOW_DATA_ROOT')
            time.sleep(.2)
        yield
    finally:
        for proc,handle,_ in reversed(children):
            if proc.poll() is None:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
                else:proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
            handle.close()


if __name__=='__main__':
    with stack(include_api=True):
        print('Phase3 A2A, MCP and Workflow API ready; Ctrl+C to stop.',flush=True)
        try:
            while True:time.sleep(1)
        except KeyboardInterrupt:pass
