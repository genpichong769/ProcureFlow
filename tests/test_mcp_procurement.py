import asyncio
import json
from datetime import date,timedelta
from mcp.shared.memory import create_connected_server_and_client_session
from mcp_server.mcp_procurement_server import create_server


def test_all_procurement_tools(db,approved,order_args,service):
    async def run():
        async with create_connected_server_and_client_session(create_server(db)) as session:
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools} == {'create_purchase_request','get_purchase_request','submit_purchase_request',
                'cancel_purchase_request','create_purchase_order','get_purchase_order','update_purchase_order_status'}
            async def call(name,args):
                response = await session.call_tool(name,args)
                assert not response.isError
                value = json.loads(response.content[0].text)
                assert value['ok'],value
                return value['data']
            draft = await call('create_purchase_request',dict(requester_id=1,department_id=1,
                required_delivery_date=(date.today()+timedelta(days=30)).isoformat(),reason='MCP test',
                items=[dict(product_id=1,quantity=1,max_unit_price='120')]))
            assert (await call('get_purchase_request',dict(request_id=draft['id'])))==draft
            assert (await call('submit_purchase_request',dict(request_id=draft['id'])))['status']=='PENDING_APPROVAL'
            assert (await call('cancel_purchase_request',dict(request_id=draft['id'])))['status']=='CANCELLED'
            po = await call('create_purchase_order',order_args)
            assert (await call('create_purchase_order',dict(request_id=approved['id'])))==po
            assert (await call('get_purchase_order',dict(purchase_order_id=po['id'])))==po
            assert len(po['items'])==2 and po['total_amount']=='400.00'
            confirmed = await call('update_purchase_order_status',dict(purchase_order_id=po['id'],status='CONFIRMED'))
            assert confirmed['status']=='CONFIRMED'
            assert service.get_purchase_order(po['id'])['status']=='CONFIRMED'
    asyncio.run(run())
