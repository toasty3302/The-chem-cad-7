"""MCP tools for Claude, Codex, OpenCode, and any stdio MCP client."""

from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .api import describe_api
from .bridge import WorkerBridge

bridge = WorkerBridge()


@asynccontextmanager
async def lifespan(_server):
    try:
        yield {}
    finally:
        await bridge.close()


mcp = FastMCP(
    "CHEMCAD",
    instructions=(
        "Use open_simulation before flowsheet tools. Start with read_only=true. "
        "For experiments use read_only=false with copy_to pointing at a new file. "
        "Streams use SI units: kelvin, absolute pascals, watts, kmol/hour. "
        "Component order is the one-based order returned by list_components. "
        "Mutations remain in memory until save_simulation. Check run results and unitop error messages. "
        "Use describe_chemcad_api for exact native signatures and enumeration values. "
        "Legacy COM arrays reserve element zero; typed arrays supplied to invoke_chemcad must include it."
    ),
    lifespan=lifespan,
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


@mcp.tool(annotations=READ)
def describe_chemcad_api(
    surface: str | None = None, method: str | None = None
) -> dict[str, Any]:
    """Browse signatures and constants extracted from the installed CHEMCAD type library. Does not start CHEMCAD."""
    return describe_api(surface, method)


@mcp.tool(annotations=WRITE)
async def connect_chemcad() -> dict[str, Any]:
    """Start an out-of-process CHEMCAD VBServer automation session and report its process ID and engine version."""
    return await bridge.request("connect")


@mcp.tool(annotations=READ)
async def chemcad_status() -> dict[str, Any]:
    """Report the automation connection, loaded file, read-only state, and simulation mode. Does not activate CHEMCAD."""
    return await bridge.request("status")


@mcp.tool(annotations=WRITE)
async def disconnect_chemcad() -> dict[str, Any]:
    """Release this MCP server's COM references. Unsaved in-memory changes are discarded."""
    return await bridge.request("disconnect")


@mcp.tool(annotations=WRITE)
async def open_simulation(
    path: str, read_only: bool = True, copy_to: str | None = None
) -> dict[str, Any]:
    """Open a .ccsim or .ccx file. Set copy_to to a NEW filename and read_only=false for editing a copy. Replaces the current loaded model."""
    return await bridge.request(
        "open_simulation", path=path, read_only=read_only, copy_to=copy_to
    )


@mcp.tool(annotations=WRITE)
async def close_simulation() -> dict[str, Any]:
    """Close the current simulation without saving in-memory edits."""
    return await bridge.request("close_simulation")


@mcp.tool(annotations=SAVE)
async def save_simulation() -> dict[str, Any]:
    """Save the current writable simulation to its loaded file. Overwrites that file; use copy_to when opening to protect the source."""
    return await bridge.request("save_simulation")


@mcp.tool(annotations=READ)
async def flowsheet_summary() -> dict[str, Any]:
    """Read components, stream connections, unit-operation categories, inlet/outlet IDs, and unit-operation errors."""
    return await bridge.request("summary")


@mcp.tool(annotations=READ)
async def list_components() -> list[dict[str, Any]]:
    """Return component names and database IDs in the flowsheet's one-based composition order."""
    return await bridge.request("components")


@mcp.tool(annotations=READ)
async def read_stream(
    stream_id: int, units: Literal["si", "internal"] = "si"
) -> dict[str, Any]:
    """Read temperature, absolute pressure, vapor mole fraction, enthalpy rate, and component flows. SI units are K, Pa, W, kmol/h."""
    return await bridge.request("read_stream", stream_id=stream_id, units=units)


@mcp.tool(annotations=WRITE)
async def write_stream(
    stream_id: int,
    temperature_k: float,
    pressure_pa: float,
    component_flows_kmol_h: list[float],
    vapor_mole_fraction: float = 0.0,
    enthalpy_w: float = 0.0,
    reflash: bool = True,
) -> dict[str, Any]:
    """Update a writable stream in SI units. Component flows follow list_components order. Reflash uses the stream's existing flash mode; edits are unsaved."""
    return await bridge.request(
        "write_stream",
        stream_id=stream_id,
        temperature_k=temperature_k,
        pressure_pa=pressure_pa,
        component_flows_kmol_h=component_flows_kmol_h,
        vapor_mole_fraction=vapor_mole_fraction,
        enthalpy_w=enthalpy_w,
        reflash=reflash,
    )


@mcp.tool(annotations=READ)
async def read_unitop_parameter(
    unitop_id: int, parameter_id: int, user_units: bool = True
) -> dict[str, Any]:
    """Read a numeric unit-operation parameter by its CHEMCAD parameter ID. Consult the equipment model's parameter documentation."""
    return await bridge.request(
        "unitop_parameter",
        unitop_id=unitop_id,
        parameter_id=parameter_id,
        user_units=user_units,
    )


@mcp.tool(annotations=WRITE)
async def write_unitop_parameter(
    unitop_id: int, parameter_id: int, value: float, user_units: bool = True
) -> dict[str, Any]:
    """Update a numeric parameter on a writable simulation and read it back. Units are current flowsheet units by default; edits are unsaved."""
    return await bridge.request(
        "unitop_parameter",
        unitop_id=unitop_id,
        parameter_id=parameter_id,
        value=value,
        user_units=user_units,
    )


@mcp.tool(annotations=WRITE)
async def run_simulation(
    mode: Literal["steady_state", "dynamic_step", "dynamic_all"] = "steady_state",
    unitop_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Run a writable simulation. Optional unitop_ids select steady-state equipment. Returns success, native error code, and runtime messages; does not save."""
    return await bridge.request("run_simulation", mode=mode, unitop_ids=unitop_ids)


@mcp.tool(annotations=READ)
async def flash_tp(
    temperature_k: float, pressure_pa: float, component_flows_kmol_h: list[float]
) -> dict[str, Any]:
    """Calculate a TP flash using the loaded model's components and thermodynamics. Returns vapor fraction, phase compositions, and enthalpy in SI units."""
    return await bridge.request(
        "flash_tp",
        temperature_k=temperature_k,
        pressure_pa=pressure_pa,
        component_flows_kmol_h=component_flows_kmol_h,
    )


@mcp.tool(annotations=WRITE)
async def invoke_chemcad(
    surface: str, method: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call a method listed by describe_chemcad_api. Arguments are keyed by native parameter name. Reference parameters return in references. For typed arrays use {type: array_r4, value: [0,...], byref: true}; reserve index zero for legacy arrays. Native return values have method-specific meanings. Lifecycle methods use dedicated tools."""
    return await bridge.request(
        "invoke", surface=surface, method=method, arguments=arguments
    )


@mcp.resource("chemcad://api")
def api_resource() -> str:
    """Recovered automation methods and enumeration constants."""
    return json.dumps(describe_api(), indent=2)


def main():
    parser = argparse.ArgumentParser(description="CHEMCAD MCP server (Windows, stdio)")
    parser.add_argument(
        "--list-api",
        action="store_true",
        help="Print the recovered API without starting CHEMCAD",
    )
    args = parser.parse_args()
    if args.list_api:
        print(json.dumps(describe_api(), indent=2))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
