"""Exercise real MCP and CHEMCAD on a copy of a vendor example."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT = Path(__file__).resolve().parents[1]
SAMPLE = Path(
    r"C:\ProgramData\Chemstations\CHEMCAD NXT\Examples\_Process Simulation Essentials\2 Phase Equilibria\1 - Flash calculations.ccsim"
)


async def run(live=False):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chemcad_mcp.server"]
    )
    results = []
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=200)
        ) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            print(
                f"Initialized {initialized.serverInfo.name}; {len(tools.tools)} tools",
                flush=True,
            )

            async def call(name, arguments=None, expect_error=False):
                start = time.monotonic()
                response = await session.call_tool(name, arguments or {})
                output = response.structuredContent
                if output is None:
                    text = "\n".join(
                        getattr(content, "text", "") for content in response.content
                    )
                    try:
                        output = json.loads(text)
                    except json.JSONDecodeError:
                        output = text
                print(
                    name,
                    "ERROR" if response.isError else "OK",
                    f"{time.monotonic() - start:.2f}s",
                    str(output)[:500],
                    flush=True,
                )
                results.append(
                    {"tool": name, "is_error": bool(response.isError), "result": output}
                )
                if bool(response.isError) != expect_error:
                    raise AssertionError(f"Unexpected result from {name}: {output}")
                return output

            await call(
                "describe_chemcad_api",
                {"surface": "streams", "method": "GetStreamByID"},
            )
            await call("chemcad_status")
            if live:
                source_hash = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
                await call("open_simulation", {"path": str(SAMPLE)})
                topology = await call("flowsheet_summary")
                assert (
                    len(topology["streams"]) == 18 and len(topology["components"]) == 4
                )
                stream = await call("read_stream", {"stream_id": 1})
                assert abs(stream["temperature"] - 373.15) < 0.01
                assert abs(stream["pressure"] - 100000) < 10
                await call(
                    "write_stream",
                    {
                        "stream_id": 1,
                        "temperature_k": 350,
                        "pressure_pa": 100000,
                        "component_flows_kmol_h": [50, 0, 0, 50],
                    },
                    expect_error=True,
                )
                flash = await call(
                    "flash_tp",
                    {
                        "temperature_k": 373.15,
                        "pressure_pa": 100000,
                        "component_flows_kmol_h": [50, 0, 0, 50],
                    },
                )
                assert 0 <= flash["vapor_mole_fraction"] <= 1
                assert (
                    abs(flash["enthalpy_w"] - stream["enthalpy_rate"])
                    < abs(stream["enthalpy_rate"]) * 0.001
                )
                for index, feed in enumerate([50, 0, 0, 50]):
                    phase_flow = sum(
                        flash[phase]["components"][index]["flow_kmol_h"]
                        for phase in ("liquid", "vapor")
                    )
                    assert abs(phase_flow - feed) < 0.001
                await call(
                    "invoke_chemcad",
                    {
                        "surface": "streams",
                        "method": "GetStreamByID",
                        "arguments": {
                            "streamID": 1,
                            "tempR": 0.0,
                            "presPsia": 0.0,
                            "moleVapFrac": 0.0,
                            "enthBtu_Hr": 0.0,
                            "compFlowLbmol_Hr": {
                                "type": "array_r4",
                                "value": [0] * 5,
                                "byref": True,
                            },
                        },
                    },
                )
                work = PROJECT / "work"
                work.mkdir(exist_ok=True)
                destination = (
                    Path(tempfile.mkdtemp(prefix="validation-", dir=work))
                    / "flash-copy.ccsim"
                )
                await call(
                    "open_simulation",
                    {
                        "path": str(SAMPLE),
                        "read_only": False,
                        "copy_to": str(destination),
                    },
                )
                unit_id = topology["unitops"][0]["id"]
                parameter = await call(
                    "read_unitop_parameter", {"unitop_id": unit_id, "parameter_id": 2}
                )
                await call(
                    "write_unitop_parameter",
                    {
                        "unitop_id": unit_id,
                        "parameter_id": 2,
                        "value": parameter["value"],
                    },
                )
                changed = await call(
                    "write_stream",
                    {
                        "stream_id": 1,
                        "temperature_k": 370,
                        "pressure_pa": 100000,
                        "component_flows_kmol_h": [50, 0, 0, 50],
                    },
                )
                assert abs(changed["temperature"] - 370) < 0.01
                run_result = await call("run_simulation")
                assert run_result["success"], run_result
                await call("save_simulation")
                await call("close_simulation")
                await call("open_simulation", {"path": str(destination)})
                persisted = await call("read_stream", {"stream_id": 1})
                assert abs(persisted["temperature"] - 370) < 0.01
                assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == source_hash
                await call("disconnect_chemcad")
                results.append(
                    {"source_unchanged": True, "validation_copy": str(destination)}
                )
    report = (
        PROJECT
        / "docs"
        / ("live-validation.json" if live else "protocol-validation.json")
    )
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Report:", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    asyncio.run(run(parser.parse_args().live))
