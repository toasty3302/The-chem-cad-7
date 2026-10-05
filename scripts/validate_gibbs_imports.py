"""Verify imported ethane actually burns in a disposable Gibbs-reactor model."""

import asyncio
import hashlib
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chemcad_mcp.installation import examples_directory


async def validate():
    examples = examples_directory()
    source = examples / "Utility and power/Gas turbine simulation.ccsim"
    donor = examples / "Gas Processing/TEG gas dehydration-regeneration.ccsim"
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, donor)}
    work = Path(__file__).resolve().parents[1] / "work"
    work.mkdir(exist_ok=True)
    output = (
        Path(tempfile.mkdtemp(prefix="gibbs-imports-", dir=work)) / "combustion.ccsim"
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chemcad_mcp.server"]
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=200)
        ) as session:
            await session.initialize()

            async def call(name, arguments=None):
                result = await session.call_tool(name, arguments or {})
                assert not result.isError, result.content
                return result.structuredContent

            try:
                await call("open_simulation", {"path": str(source)})
                zero = await call("read_stream", {"stream_id": 1})
                assert zero["components"][4]["flow"] == 0
                await call("close_simulation")
                await call(
                    "create_simulation_from_template",
                    {
                        "template_path": str(source),
                        "output_path": str(output),
                        "acknowledge_stale_drawing": True,
                        "replace_topology": True,
                        "unitops": [
                            {"id": 1, "prototype_id": 1, "inlets": [2], "outlets": [3]},
                            {
                                "id": 2,
                                "prototype_id": 2,
                                "inlets": [1, 3],
                                "outlets": [4],
                            },
                            {"id": 3, "prototype_id": 3, "inlets": [4], "outlets": [5]},
                        ],
                        "connections": [
                            {"id": 1, "source_unitop": 0, "target_unitop": 2},
                            {"id": 2, "source_unitop": 0, "target_unitop": 1},
                            {"id": 3, "source_unitop": 1, "target_unitop": 2},
                            {"id": 4, "source_unitop": 2, "target_unitop": 3},
                            {"id": 5, "source_unitop": 3, "target_unitop": 0},
                        ],
                        "component_imports": [
                            {
                                "id": 3,
                                "donor_path": str(donor),
                                "zero_flow_stream_id": 1,
                                "zero_flow_position": 5,
                            }
                        ],
                    },
                )
                await call("open_simulation", {"path": str(output), "read_only": False})
                feed = await call("read_stream", {"stream_id": 1})
                await call(
                    "write_feed",
                    {
                        "stream_id": 2,
                        "temperature_k": 300,
                        "pressure_pa": 101325,
                        "total_flow_kmol_h": 300,
                        "mole_fractions": {"46": 0.79, "47": 0.21},
                    },
                )
                await call(
                    "write_feed",
                    {
                        "stream_id": 1,
                        "temperature_k": feed["temperature"],
                        "pressure_pa": feed["pressure"],
                        "total_flow_kmol_h": 20,
                        "mole_fractions": {"2": 0.95, "3": 0.05},
                    },
                )
                run = await call("run_simulation", {"unitop_ids": [1, 2, 3]})
                assert run["success"], run
                product = await call("read_stream", {"stream_id": 5})
                print(
                    f"Combustor temperature: {product['temperature']:.3f} K", flush=True
                )
                ethane = next(c["flow"] for c in product["components"] if c["id"] == 3)
                print(
                    f"Ethane: feed=1 kmol/h, combustor product={ethane:.9g} kmol/h",
                    flush=True,
                )
                assert ethane < 1e-5, (
                    "Imported ethane is silently inert; extend the Gibbs element matrix"
                )
                await call("save_simulation")
                await call("close_simulation")
                await call("open_simulation", {"path": str(output)})
                reopened = await call("read_stream", {"stream_id": 5})
                assert (
                    next(c["flow"] for c in reopened["components"] if c["id"] == 3)
                    < 1e-5
                )
            finally:
                await call("disconnect_chemcad")
                for path, expected in hashes.items():
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


if __name__ == "__main__":
    asyncio.run(validate())
