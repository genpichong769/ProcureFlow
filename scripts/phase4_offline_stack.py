"""Own the six processes used by deterministic Phase4 A2A/MCP evaluation."""
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
        return sock.connect_ex((get_settings().agent_host, port)) == 0


@contextmanager
def stack():
    settings = get_settings()
    specs = [(f'mcp_server.mcp_{role}_server', [], getattr(settings, f'mcp_{role}_port'))
             for role in ('budget', 'supplier', 'compliance')]
    specs += [('scripts.phase4_offline_agent_server', [role], getattr(settings, f'a2a_{role}_port'))
              for role in ('budget', 'supplier', 'compliance')]
    if any(listening(port) for _, _, port in specs):
        raise RuntimeError('Phase4 offline ports occupied')
    logdir = settings.require_persistent_path(settings.logs_dir / 'phase4')
    logdir.mkdir(parents=True, exist_ok=True)
    children = []
    try:
        for module, arguments, port in specs:
            handle = (logdir / (module.replace('.', '_') + ('_' + arguments[0] if arguments else '') + '.log')).open(
                'w', encoding='utf-8')
            proc = subprocess.Popen(
                [sys.executable, '-m', module, *arguments], cwd=ROOT, stdout=handle, stderr=handle,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            children.append((proc, handle, port))
        deadline = time.monotonic() + 45
        while not all(listening(port) for _, _, port in children):
            if any(proc.poll() is not None for proc, _, _ in children) or time.monotonic() > deadline:
                raise RuntimeError('Phase4 offline stack failed; inspect logs under PROCUREFLOW_DATA_ROOT')
            time.sleep(.2)
        yield
    finally:
        for proc, handle, _ in reversed(children):
            if proc.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            handle.close()


if __name__ == '__main__':
    with stack():
        print('Phase4 deterministic A2A/MCP stack ready; Ctrl+C to stop.', flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
