"""Actual loopback HTTP transport, MCP handshake, discovery and tool execution."""
import asyncio
from contextlib import contextmanager
import importlib
import json
import socket
from threading import Thread
import time
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@contextmanager
def live_server(app):
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on'))
    thread = Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('HTTP server failed to start')
            time.sleep(0.05)
        assert server.started
        yield f'http://127.0.0.1:{port}/mcp'
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize('name,tool,args,count',[
    ('budget','get_department_budget',{'department':1},3),
    ('supplier','search_supplier_quotes',{'product':1,'quantity':5,'max_unit_price':'120','max_delivery_days':10},3),
    ('compliance','evaluate_procurement_compliance',{'department':1,'supplier_id':1,'category':'IT','total_amount':'1000','valid_quote_count':3},3),
    ('procurement','create_purchase_order',None,7),
])
def test_real_http_transport(db,order_args,name,tool,args,count):
    module = importlib.import_module('mcp_server.mcp_'+name+'_server')
    mcp = module.create_server(db)
    async def run(url):
        async with streamablehttp_client(url) as (read,write,_):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert len(tools)==count
                assert not any('sql' in t.inputSchema.get('properties',{}) for t in tools)
                response = await session.call_tool(tool,args if args is not None else order_args)
                assert not response.isError
                result = json.loads(response.content[0].text)
                assert result['ok'],result
                if name=='procurement':
                    assert result['data']['total_amount']=='400.00'
                    retry = await session.call_tool(tool,{'request_id':order_args['request_id']})
                    assert json.loads(retry.content[0].text)['data']['id']==result['data']['id']
    with live_server(mcp.streamable_http_app()) as url:
        asyncio.run(run(url))
