"""Validate model-building MCP tools on disposable licensed examples only."""

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chemcad_mcp.installation import examples_directory

PROJECT = Path(__file__).resolve().parents[1]


async def validate(headers=None):
    examples = examples_directory()
    source = examples / "Utility and power/Gas turbine simulation.ccsim"
    donor = examples / "Gas Processing/TEG gas dehydration-regeneration.ccsim"
    exchanger = examples / "Utility and power/Industrial power plant.ccsim"
    reactor = (
        examples / "_Process Simulation Essentials/4 Reactors/1 - Reactor models.ccsim"
    )
    originals = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (source, donor, exchanger, reactor)
    }
    (PROJECT / "work").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="model-tools-", dir=PROJECT / "work"))
    reports = []
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "chemcad_mcp.server"]
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=200)
        ) as session:
            await session.initialize()
            print(f"Tools: {len((await session.list_tools()).tools)}", flush=True)

            async def call(name, arguments=None, expect_error=False):
                response = await session.call_tool(name, arguments or {})
                output = response.structuredContent
                if output is None:
                    content = "\n".join(
                        getattr(c, "text", "") for c in response.content
                    )
                    try:
                        output = json.loads(content)
                    except json.JSONDecodeError:
                        output = content
                reports.append(
                    {"tool": name, "error": bool(response.isError), "result": output}
                )
                print(
                    name,
                    "ERROR" if response.isError else "OK",
                    str(output)[:250],
                    flush=True,
                )
                assert bool(response.isError) == expect_error, output
                return output

            try:
                await call("list_simulation_templates", {"query": "Gas turbine"})
                await call("inspect_simulation_archive", {"path": str(source)})
                if headers:
                    await call(
                        "read_xlsx_headers",
                        {
                            "path": headers,
                            "sheet_names": [
                                "Air",
                                "Gas",
                                "Engine",
                                "Generator",
                                "Stm",
                                "Add'n tags",
                            ],
                        },
                    )
                await call("open_simulation", {"path": str(source)})
                feed = await call("read_stream", {"stream_id": 1})
                assert feed["components"][4]["flow"] == 0
                await call(
                    "configure_unitop",
                    {"unitop_id": 1, "parameters": {"efficiency": 0.8}},
                    expect_error=True,
                )
                await call("close_simulation")
                output = directory / "constructed.ccsim"
                imports = [
                    {"id": cid, "donor_path": str(donor)}
                    for cid in [3, 4, 6, 8, 10]
                ]
                imports[0].update(zero_flow_stream_id=1, zero_flow_position=5)
                await call(
                    "create_simulation_from_template",
                    {
                        "template_path": str(source),
                        "output_path": str(output),
                        "acknowledge_stale_drawing": True,
                        "unitops": [
                            {
                                "id": 9,
                                "prototype_id": 2,
                                "label": "Disposable added mixer",
                                "inlets": [10],
                                "outlets": [11],
                            }
                        ],
                        "connections": [
                            {"id": 10, "source_unitop": 8, "target_unitop": 9},
                            {"id": 11, "source_unitop": 9, "target_unitop": 0},
                        ],
                        "component_imports": imports,
                    },
                )
                await call("open_simulation", {"path": str(output), "read_only": False})
                topology = await call("flowsheet_summary")
                assert (
                    len(topology["unitops"]) == 9 and len(topology["components"]) == 13
                )
                assert all(not c["name"].isdigit() for c in topology["components"])
                for stream_id in range(1, 12):
                    stream = await call("read_stream", {"stream_id": stream_id})
                    assert all(c["flow"] == 0 for c in stream["components"][8:])
                await call(
                    "flash_tp",
                    {
                        "temperature_k": 350,
                        "pressure_pa": 101325,
                        "component_flows_kmol_h": [0] * 8 + [1, 0, 0, 0, 0],
                    },
                )
                catalog = await call("unitop_parameter_catalog", {"unitop_id": 1})
                efficiency = next(
                    p for p in catalog["parameters"] if p["name"] == "efficiency"
                )["value"]
                assert 0 < efficiency <= 1, "Skip the legacy equipment-ID header"
                await call(
                    "configure_unitop",
                    {"unitop_id": 1, "parameters": {"efficiency": efficiency}},
                )
                fuel = await call("read_stream", {"stream_id": 1})
                flows = {c["name"]: c["flow"] for c in fuel["components"] if c["flow"]}
                await call(
                    "write_stream_by_component",
                    {
                        "stream_id": 1,
                        "temperature_k": fuel["temperature"],
                        "pressure_pa": fuel["pressure"],
                        "component_flows_kmol_h": flows,
                    },
                )
                total = sum(flows.values())
                await call(
                    "write_feed",
                    {
                        "stream_id": 1,
                        "temperature_k": fuel["temperature"],
                        "pressure_pa": fuel["pressure"],
                        "total_flow_kmol_h": total,
                        "mole_fractions": {
                            name: flow / total for name, flow in flows.items()
                        },
                    },
                )
                run = await call("run_simulation")
                assert run["success"], run
                results = await call("simulation_results")
                assert not any(u["error_code"] for u in results["unitops"])
                assert len(results["unitop_stream_balances"]) == 9
                sweep = await call(
                    "run_parameter_sensitivity",
                    {
                        "unitop_id": 1,
                        "parameter_id": 5,
                        "values": [efficiency * 0.99, efficiency],
                        "stream_ids": [10, 11],
                    },
                )
                assert sweep["baseline_run"]["success"] and all(
                    p["usable"] for p in sweep["points"]
                )
                await call("save_simulation")
                await call("close_simulation")
                await call("open_simulation", {"path": str(output)})
                reopened = await call("flowsheet_summary")
                assert (
                    len(reopened["unitops"]) == 9 and len(reopened["components"]) == 13
                )
                await call("close_simulation")

                # A new heat-exchanger prototype from a different component list.
                hx_output = directory / "exchanger.ccsim"
                await call(
                    "create_simulation_from_template",
                    {
                        "template_path": str(source),
                        "output_path": str(hx_output),
                        "acknowledge_stale_drawing": True,
                        "unitops": [
                            {
                                "id": 9,
                                "prototype_path": str(exchanger),
                                "prototype_id": 14,
                                "label": "Disposable HRSG exchanger",
                                "inlets": [10, 11],
                                "outlets": [12, 13],
                            }
                        ],
                        "connections": [
                            {"id": 10, "source_unitop": 8, "target_unitop": 9},
                            {"id": 11, "source_unitop": 0, "target_unitop": 9},
                            {"id": 12, "source_unitop": 9, "target_unitop": 0},
                            {"id": 13, "source_unitop": 9, "target_unitop": 0},
                        ],
                    },
                )
                await call(
                    "open_simulation", {"path": str(hx_output), "read_only": False}
                )
                await call("unitop_parameter_catalog", {"unitop_id": 9})
                await call(
                    "write_feed",
                    {
                        "stream_id": 11,
                        "temperature_k": 350,
                        "pressure_pa": 2000000,
                        "total_flow_kmol_h": 100,
                        "mole_fractions": {"Water": 1},
                    },
                )
                await call(
                    "configure_unitop",
                    {
                        "unitop_id": 9,
                        "user_units": False,
                        "parameters": {
                            "1st_stream_t_out": 0,
                            "2nd_stream_t_out": 0,
                            "1st_stream_vf_out": 0,
                            "2nd_stream_vf_out": 0,
                            "input_heat_duty": 50000 * 3600 / 1055.05585262,
                            "simulation_mode": 0,
                        },
                    },
                )
                hx_run = await call("run_simulation")
                hx_results = await call(
                    "simulation_results", {"stream_ids": [10, 11, 12, 13]}
                )
                assert hx_run["success"], hx_results["unitops"]
                by_id = {s["id"]: s for s in hx_results["stream_results"]}
                hot_duty = by_id[10]["enthalpy_rate"] - by_id[12]["enthalpy_rate"]
                cold_duty = by_id[13]["enthalpy_rate"] - by_id[11]["enthalpy_rate"]
                assert abs(abs(hot_duty) - 50000) < 100
                assert abs(hot_duty - cold_duty) < 100
                await call("save_simulation")
                await call("close_simulation")
                await call("open_simulation", {"path": str(hx_output)})
                assert len((await call("flowsheet_summary"))["unitops"]) == 9
                persisted = await call(
                    "read_unitop_parameter",
                    {"unitop_id": 9, "parameter_id": 9, "user_units": False},
                )
                assert abs(persisted["value"] * 1055.05585262 / 3600 - 50000) < 1
                await call("close_simulation")

                # Native REAC helper: preserve the example's existing reaction
                # while resolving species by database IDs, not positions.
                await call(
                    "open_simulation",
                    {
                        "path": str(reactor),
                        "copy_to": str(directory / "reactor.ccsim"),
                        "read_only": False,
                    },
                )
                reactor_components = (await call("flowsheet_summary"))["components"]
                reactor_catalog = await call(
                    "unitop_parameter_catalog", {"unitop_id": 5}
                )
                params_by_name = {
                    p["name"]: p["value"] for p in reactor_catalog["parameters"]
                }
                key_position = int(params_by_name["key_component"])
                await call(
                    "configure_stoichiometric_reactor",
                    {
                        "unitop_id": 5,
                        "stoichiometry": {
                            str(c["id"]): params_by_name[f"comp_{i + 1}"]
                            for i, c in enumerate(reactor_components)
                        },
                        "key_component": str(
                            reactor_components[key_position - 1]["id"]
                        ),
                        "conversion": params_by_name["frac_conversion"],
                        "thermal_mode": int(params_by_name["thermal_mode"]),
                    },
                )
                reactor_run = await call("run_simulation", {"unitop_ids": [5]})
                assert reactor_run["success"], reactor_run
                await call("save_simulation")
                await call("close_simulation")
            finally:
                await call("disconnect_chemcad")
                for path, digest in originals.items():
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
                (directory / "results.json").write_text(
                    json.dumps(reports, indent=2), encoding="utf-8"
                )
                print(f"Report: {directory}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", help="Optional workbook; reads only its first row")
    asyncio.run(validate(parser.parse_args().headers))
