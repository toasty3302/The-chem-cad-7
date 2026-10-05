"""Check native shaft-power units against a disposable example's stream energy."""

import argparse
import asyncio
import hashlib
import json
import math
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chemcad_mcp.installation import examples_directory

BTU_HR_TO_W = 1055.05585262 / 3600
HP_TO_W = 745.6998715822702


async def validate(conversion):
    source = examples_directory() / "Utility and power/Gas turbine simulation.ccsim"
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    directory = Path(__file__).resolve().parents[1] / "work"
    directory.mkdir(exist_ok=True)
    copy = Path(tempfile.mkdtemp(prefix="power-units-", dir=directory)) / source.name
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chemcad_mcp.server"]
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=200)
        ) as session:
            await session.initialize()

            async def call(name, arguments=None):
                response = await session.call_tool(name, arguments or {})
                assert not response.isError, response.content
                return response.structuredContent

            try:
                await call(
                    "open_simulation",
                    {
                        "path": str(source),
                        "copy_to": str(copy),
                        "read_only": False,
                    },
                )
                # One compressor is enough to distinguish internal Btu/h from
                # the example's displayed horsepower, without any controller.
                run = await call("run_simulation", {"unitop_ids": [1]})
                assert run["success"], run
                catalog = await call("unitop_parameter_catalog", {"unitop_id": 1})
                power_entry = next(
                    p for p in catalog["parameters"] if p["name"] == "actual_power"
                )
                power = await call(
                    "read_unitop_parameter",
                    {
                        "unitop_id": 1,
                        "parameter_id": power_entry["parameter_id"],
                        "user_units": False,
                    },
                )
                results = await call("simulation_results", {"stream_ids": [2, 3]})
                balance = next(
                    b for b in results["unitop_stream_balances"] if b["unitop_id"] == 1
                )
                native_w = power["value"] * conversion
                delta_w = balance["net_energy_into_streams_w"]
                print(
                    json.dumps(
                        {
                            "actual_power_parameter_id": power_entry["parameter_id"],
                            "displayed_units": power_entry["current_units"],
                            "displayed_value": power_entry["value"],
                            "internal_value": power["value"],
                            "converted_w": native_w,
                            "stream_enthalpy_gain_w": delta_w,
                            "relative_difference": (native_w - delta_w) / delta_w,
                        },
                        indent=2,
                    ),
                    flush=True,
                )
                assert math.isclose(native_w, delta_w, rel_tol=1e-4), (
                    "Shaft power does not match the adiabatic stream energy gain. "
                    "Internal COMP/EXPN power is Btu/h, not displayed horsepower."
                )
            finally:
                await call("disconnect_chemcad")
                assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversion", choices=["btu/h", "hp"], default="btu/h")
    args = parser.parse_args()
    asyncio.run(validate(BTU_HR_TO_W if args.conversion == "btu/h" else HP_TO_W))
