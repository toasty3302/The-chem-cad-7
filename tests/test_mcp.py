import asyncio
import json
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_protocol_without_activating_chemcad():
    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "chemcad_mcp.server"]
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(
                reader, writer, read_timeout_seconds=timedelta(seconds=45)
            ) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "CHEMCAD"
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert "write_stream" in tools and "flash_tp" in tools
                assert tools["read_stream"].annotations.readOnlyHint is True
                assert tools["save_simulation"].annotations.destructiveHint is True
                status = await session.call_tool("chemcad_status", {})
                assert not status.isError
                assert json.loads(status.content[0].text)["connected"] is False
                api = await session.call_tool(
                    "describe_chemcad_api",
                    {"surface": "streams", "method": "GetStreamByID"},
                )
                assert not api.isError
                assert json.loads(api.content[0].text)["dispid"] == 3
                resource = await session.read_resource("chemcad://api")
                assert "SPEC_MOLE_RATE" in resource.contents[0].text

    asyncio.run(scenario())
