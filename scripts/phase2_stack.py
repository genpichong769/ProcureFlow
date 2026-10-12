"""Own only seven child processes; reuse the existing Docker MySQL without writes."""
from contextlib import contextmanager
import os
import socket
import subprocess
import sys
import time
from config import ROOT, get_settings


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex((get_settings().agent_host,port))==0


@contextmanager
def stack():
    settings=get_settings()
    modules=[(f'mcp_server.mcp_{r}_server',getattr(settings,f'mcp_{r}_port')) for r in ('budget','supplier','compliance')]
    modules += [(f'a2a_server.{r}_agent_server',getattr(settings,f'a2a_{r}_port')) for r in ('budget','supplier','compliance','procurement')]
    if any(listening(port) for _,port in modules):
        raise RuntimeError('Phase2 ports occupied; stop their owner before launching a second stack')
    logdir=settings.require_persistent_path(settings.logs_dir/'agents')
    logdir.mkdir(parents=True,exist_ok=True)
    children=[]
    try:
        for module,port in modules:
            handle=(logdir/(module+'.log')).open('w',encoding='utf-8')
            proc=subprocess.Popen([sys.executable,'-m',module],cwd=ROOT,stdout=handle,stderr=handle,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append((proc,handle,port))
        deadline=time.monotonic()+45
        while not all(listening(p) for _,_,p in children):
            if any(proc.poll() is not None for proc,_,_ in children) or time.monotonic()>deadline:
                raise RuntimeError('Phase2 service startup failed; inspect logs under PROCUREFLOW_DATA_ROOT')
            time.sleep(.2)
        yield
    finally:
        for proc,handle,_ in reversed(children):
            if proc.poll() is None:
                if os.name=='nt':
                    # Windows venv launchers spawn the base Python process. Stop this owned tree.
                    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
                else:proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
            handle.close()


if __name__=='__main__':
    with stack():
        print('Four A2A agents and three read-only MCP servers ready; Ctrl+C to stop.',flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
