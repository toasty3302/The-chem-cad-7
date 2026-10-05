"""MCP tools for Claude, Codex, OpenCode, and any stdio MCP client."""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .api import describe_api
from .archives import ModelArchive, create_model, list_templates
from .bridge import WorkerBridge
from .datasets import read_xlsx_headers as inspect_headers
from .datasets import read_xlsx_rows as inspect_rows
from .engineering import chp_metrics
from .engineering import screen_operating_points as screen_points

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
        " Discover local licensed templates with list_simulation_templates. Experimental archive construction "
        "does not regenerate the GUI drawing; explicitly acknowledge this limitation. Component imports require "
        "ordinary pure-property records from local donor archives, not arbitrary component-list XML edits. "
        "Use unitop_parameter_catalog for named parameters and current units. Never fit outage/startup data as steady state."
    ),
    lifespan=lifespan,
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


@mcp.tool(annotations=READ)
async def list_simulation_templates(
    directory: str | None = None,
    query: str = "",
    required_component_ids: list[int] | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Discover local licensed .ccsim examples by name/path and selected component IDs. Does not open CHEMCAD or ship vendor files."""
    return await asyncio.to_thread(
        list_templates, directory, query, required_component_ids, limit
    )


@mcp.tool(annotations=READ)
async def inspect_simulation_archive(path: str) -> dict[str, Any]:
    """Inspect logical .ccsim equipment, endpoints and selected component IDs without opening CHEMCAD. Numeric fields remain opaque."""
    return await asyncio.to_thread(lambda: ModelArchive(path).describe())


@mcp.tool(annotations=WRITE)
async def create_simulation_from_template(
    template_path: str,
    output_path: str,
    unitops: list[dict[str, Any]] | None = None,
    connections: list[dict[str, Any]] | None = None,
    component_imports: list[dict[str, Any]] | None = None,
    replace_topology: bool = False,
    acknowledge_stale_drawing: bool = False,
) -> dict[str, Any]:
    """Create a NEW .ccsim copy or experimental calculation topology; refuses overwrite and does not open CHEMCAD. Unitops: {id,prototype_id,prototype_path?,label?,inlets:[IDs],outlets:[IDs]}. Connections: {id,source_unitop,target_unitop,label?,prototype_stream_id?}; endpoint 0=boundary. Component imports append {id,donor_path}; first import also needs zero_flow_stream_id and zero_flow_position identifying a template component value verified zero with read_stream. Pure-property import needs Windows 32-bit Jet; BIPs/custom/electrolytes unsupported. Modified topology retains a STALE GUI drawing: acknowledge explicitly. Configure inherited specifications via COM, run, inspect and save/reopen on a disposable model before trusting it. See README."""
    return await asyncio.to_thread(
        create_model,
        template_path,
        output_path,
        unitops,
        connections,
        component_imports,
        replace_topology,
        acknowledge_stale_drawing,
    )


@mcp.tool(annotations=READ)
async def read_xlsx_headers(
    path: str, sheet_names: list[str] | None = None
) -> dict[str, Any]:
    """Read only row 1 of selected workbook sheets locally; default all sheets. Returns cell columns/tag names, not measurements or verified units. No uploads."""
    return await asyncio.to_thread(inspect_headers, path, sheet_names)


@mcp.tool(annotations=READ)
def screen_operating_points(
    points: list[dict[str, Any]],
    excluded_intervals: list[dict[str, str]] | None = None,
    transient_buffer_minutes: float = 30.0,
) -> dict[str, Any]:
    """Screen supplied one-turbine observations {timestamp:ISO,electrical_power_kw,fuel_heat_input_kw}. Exclusions {start:ISO,end:ISO} and startup/shutdown buffers are omitted from efficiencies. Reject nonpositive/nonfinite fuel or power. Does not read measurements from any file; passing is not proof of steady state."""
    return screen_points(points, excluded_intervals, transient_buffer_minutes)


@mcp.tool(annotations=READ)
async def read_xlsx_rows(
    path: str,
    sheet_name: str,
    start_row: int = 2,
    count: int = 30,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Read an explicitly selected measurement window locally: up to 1000 rows from one sheet. Optional columns are Excel letters; timestamps remain raw serials/text with the date system reported. Cached formula values only. No uploads, automatic full-dataset scan or unit/stability assumptions."""
    return await asyncio.to_thread(
        inspect_rows, path, sheet_name, start_row, count, columns
    )


@mcp.tool(annotations=READ)
def calculate_chp_metrics(
    fuel_heat_input_w: float,
    turbine_shaft_power_w: float,
    compressor_shaft_power_w: float,
    recovered_heat_w: float = 0.0,
    gearbox_efficiency: float = 1.0,
    generator_efficiency: float = 1.0,
    auxiliary_power_w: float = 0.0,
    duct_fuel_heat_input_w: float = 0.0,
) -> dict[str, Any]:
    """Calculate electrical and total CHP efficiency separately from explicit positive watt inputs. Net electrical=(turbine-compressor)*gearbox*generator-auxiliary. Include duct firing in fuel denominator and use one LHV/HHV basis. Returns no efficiency for offline/invalid points; does not infer shaft power or heat from undocumented CHEMCAD parameters."""
    return chp_metrics(
        fuel_heat_input_w,
        turbine_shaft_power_w,
        compressor_shaft_power_w,
        recovered_heat_w,
        gearbox_efficiency,
        generator_efficiency,
        auxiliary_power_w,
        duct_fuel_heat_input_w,
    )


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


@mcp.tool(annotations=READ)
async def unitop_parameter_catalog(
    unitop_id: int, include_values: bool = True
) -> dict[str, Any]:
    """Read named parameter IDs, current units and optional values from this licensed CHEMCAD installation. Enum mode meanings require equipment help; labels do not define them."""
    return await bridge.request(
        "unitop_catalog", unitop_id=unitop_id, include_values=include_values
    )


@mcp.tool(annotations=WRITE)
async def configure_unitop(
    unitop_id: int, parameters: dict[str, float], user_units: bool = True
) -> dict[str, Any]:
    """Set several equipment parameters by catalog name or numeric ID string. Validates all names/numbers first; attempts rollback on native failure. Uses current flowsheet units by default, NOT SI; does not run or save."""
    return await bridge.request(
        "configure_unitop",
        unitop_id=unitop_id,
        parameters=parameters,
        user_units=user_units,
    )


@mcp.tool(annotations=WRITE)
async def write_stream_by_component(
    stream_id: int,
    temperature_k: float,
    pressure_pa: float,
    component_flows_kmol_h: dict[str, float],
    reflash: bool = True,
) -> dict[str, Any]:
    """Write SI stream inputs using component names or databank IDs as keys (never positions). Unspecified components become zero; unknown/duplicate keys are rejected. Unsaved."""
    return await bridge.request(
        "write_stream_by_component",
        stream_id=stream_id,
        temperature_k=temperature_k,
        pressure_pa=pressure_pa,
        component_flows_kmol_h=component_flows_kmol_h,
        reflash=reflash,
    )


@mcp.tool(annotations=WRITE)
async def write_feed(
    stream_id: int,
    temperature_k: float,
    pressure_pa: float,
    total_flow_kmol_h: float,
    mole_fractions: dict[str, float],
) -> dict[str, Any]:
    """Set a boundary feed from total kmol/h and mole fractions keyed by component names/IDs. Fractions must sum to 1, not 100. K and absolute Pa; reflash then read back. Unsaved."""
    return await bridge.request(
        "write_feed",
        stream_id=stream_id,
        temperature_k=temperature_k,
        pressure_pa=pressure_pa,
        total_flow_kmol_h=total_flow_kmol_h,
        mole_fractions=mole_fractions,
    )


@mcp.tool(annotations=WRITE)
async def configure_stoichiometric_reactor(
    unitop_id: int,
    stoichiometry: dict[str, float],
    key_component: str,
    conversion: float,
    thermal_mode: int,
    temperature: float | None = None,
    pressure: float | None = None,
    user_units: bool = True,
) -> dict[str, Any]:
    """Configure REAC (not GIBS/EREA) with named/ID stoichiometry: negative reactants, positive products. Key reactant uses database ID/name; conversion 0..1. thermal_mode is the documented native enum, not guessed here. Temperature/pressure use current flowsheet units by default. Clears unspecified coefficients. Caller must verify atom balance. Unsaved."""
    return await bridge.request(
        "configure_reactor",
        unitop_id=unitop_id,
        stoichiometry=stoichiometry,
        key_component=key_component,
        conversion=conversion,
        thermal_mode=thermal_mode,
        temperature=temperature,
        pressure=pressure,
        user_units=user_units,
    )


@mcp.tool(annotations=READ)
async def simulation_results(stream_ids: list[int] | None = None) -> dict[str, Any]:
    """Read topology/errors and SI stream outputs with per-equipment enthalpy/component-flow differences. These are stream differences, NOT energy closure residuals (external heat/work not included). Reaction species moles need not be conserved. Up to 200 streams."""
    return await bridge.request("results", stream_ids=stream_ids)


@mcp.tool(annotations=WRITE)
async def run_parameter_sensitivity(
    unitop_id: int,
    parameter_id: int,
    values: list[float],
    stream_ids: list[int],
    user_units: bool = True,
) -> dict[str, Any]:
    """Sweep one documented numeric equipment parameter (1..40 values), run steady state, capture up to 20 streams, flag failed runs. Finally restore the original parameter and rerun baseline, even on failure. Unsaved; calculated baseline outputs may change. Units are current flowsheet units by default."""
    return await bridge.request(
        "sensitivity",
        unitop_id=unitop_id,
        parameter_id=parameter_id,
        values=values,
        stream_ids=stream_ids,
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
