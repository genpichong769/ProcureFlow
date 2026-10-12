import asyncio
import json
from mcp.shared.memory import create_connected_server_and_client_session


def run_tools(server,calls,expected_names):
    async def run():
        async with create_connected_server_and_client_session(server) as session:
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools}==set(expected_names)
            assert not any('sql' in t.inputSchema.get('properties',{}) for t in tools)
            outputs = []
            for name,args in calls:
                response = await session.call_tool(name,args)
                assert not response.isError, response
                outputs.append(json.loads(response.content[0].text))
            return outputs
    return asyncio.run(run())
