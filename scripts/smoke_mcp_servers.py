"""Start four real CLI servers on default ports, inspect and query them, then stop owned processes.
This smoke test reads only the main dataset; write/rollback tests live in procureflow_test.
"""
import asyncio
import importlib
import json
import os
import socket
import subprocess
import sys
import time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from config import ROOT, get_settings

SERVERS = [('budget',8001,'get_department_budget',{'department':1,'fiscal_year':2026}),
           ('supplier',8002,'search_supplier_quotes',{'product':1,'quantity':5,'max_unit_price':'100000','max_delivery_days':30}),
           ('compliance',8003,'evaluate_procurement_compliance',{'department':1,'supplier_id':1,'category':'IT','total_amount':'1000','valid_quote_count':3}),
           ('procurement',8004,'get_purchase_order',{'purchase_order_id':1})]


def listening(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1',port))==0


async def inspect(name,port,tool,args):
    async with streamablehttp_client(f'http://127.0.0.1:{port}/mcp') as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            names = [t.name for t in tools]
            assert all('sql' not in t.inputSchema.get('properties',{}) for t in tools)
            response = await session.call_tool(tool,args)
            assert not response.isError
            data = json.loads(response.content[0].text)
            assert data['ok']
            return dict(server=name,port=port,result='PASS',tools=names,tested_tool=tool)


def main():
    if any(listening(s[1]) for s in SERVERS):
        raise SystemExit('A required port is in use; refusing to interfere with existing processes.')
    processes, logs = [], []
    settings = get_settings()
    log_dir = settings.require_persistent_path(settings.logs_dir / 'mcp')
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        for name,port,_,_ in SERVERS:
            log = (log_dir/f'mcp-{name}.log').open('wb')
            logs.append(log)
            processes.append(subprocess.Popen([sys.executable,'-m',f'mcp_server.mcp_{name}_server'],cwd=ROOT,
                stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        for _ in range(100):
            if all(listening(s[1]) for s in SERVERS):
                break
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('MCP server exited during startup.')
            time.sleep(0.1)
        async def run():
            return await asyncio.gather(*(inspect(*s) for s in SERVERS))
        results = asyncio.run(run())
        (ROOT/'reports/MCP_HTTP_SMOKE.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=True))
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        for log in logs:
            log.close()


if __name__=='__main__':
    main()
