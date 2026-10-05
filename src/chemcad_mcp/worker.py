"""One STA process owns all COM objects. Its pipes carry JSON only."""

from __future__ import annotations

import gc
import json
import math
import os
import shutil
import sys
import traceback
from pathlib import Path

from .api import SURFACES, describe_api
from .windows import ensure_windows_environment

BTU_HR_TO_W = 1055.05585262 / 3600
LBMOL_TO_KMOL = 0.45359237
PSIA_TO_PA = 6894.757293168


def finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if hasattr(value, "Invoke"):
        return {"com_object": True}
    raise ValueError(f"Unsupported COM result: {type(value).__name__}")


class Automation:
    def __init__(self):
        import pythoncom
        import pywintypes
        from win32com.client import VARIANT

        self.com, self.iid, self.variant = pythoncom, pywintypes.IID, VARIANT
        self.root = None
        self.children = {}
        self.dispatch_ids = {}
        self.path = None
        self.read_only = True

    def connect(self):
        if self.root is None:
            ensure_windows_environment()
            print("Activating CHEMCAD.VBServer", file=sys.stderr, flush=True)
            # Literal CLSID works from 64-bit Python with CHEMCAD's 32-bit registration.
            self.root = self.com.CoCreateInstance(
                self.iid("{2B03C5E1-25B6-11D4-BBD3-0050DACD255C}"),
                None,
                self.com.CLSCTX_LOCAL_SERVER,
                self.com.IID_IDispatch,
            )
            print("CHEMCAD.VBServer activated", file=sys.stderr, flush=True)
        return self.status()

    def status(self):
        result = {
            "connected": self.root is not None,
            "simulation_path": self.path,
            "read_only": self.read_only,
            "platform": sys.platform,
        }
        if self.root is not None:
            result["engine_version"] = self.call("server", "GetAppVersion")
            result["work_directory"] = self.call("server", "GetWorkDir")
            result["simulation_mode"] = self.call("server", "GetSimulationMode")
            result["pid"] = self.call("server", "pid")
        return result

    def disconnect(self):
        self.children.clear()
        self.dispatch_ids.clear()
        self.root = None
        self.path = None
        self.read_only = True
        gc.collect()
        return {"connected": False}

    def target(self, surface):
        if self.root is None:
            self.connect()
        if surface == "server":
            return self.root
        if self.path is None:
            raise ValueError("Open a simulation first")
        if surface not in self.children:
            getter = SURFACES[surface][1]
            obj = self.call("server", getter)
            if obj is None:
                raise RuntimeError(
                    f"CHEMCAD did not provide the {surface} interface; check the simulation and license"
                )
            self.children[surface] = obj
        return self.children[surface]

    def ref(self, vartype, value=0):
        return self.variant(self.com.VT_BYREF | vartype, value)

    def array(self, values, vartype=None):
        # Old automation routines address SAFEARRAY elements 1..N even when LBound=0.
        if vartype is None:
            vartype = self.com.VT_R4
        return self.ref(self.com.VT_ARRAY | vartype, [0] + list(values))

    def call(self, surface, method, *args):
        info = describe_api(surface, method)
        if len(args) != len(info["parameters"]):
            raise ValueError(
                f"{surface}.{method} requires {len(info['parameters'])} arguments"
            )
        obj = self.target(surface)
        key = (surface, method)
        if os.environ.get("CHEMCAD_MCP_DEBUG") == "1":
            print(f"COM resolving {surface}.{method}", file=sys.stderr, flush=True)
        if key not in self.dispatch_ids:
            self.dispatch_ids[key] = obj.GetIDsOfNames(method)
        if os.environ.get("CHEMCAD_MCP_DEBUG") == "1":
            print(
                f"COM invoking {surface}.{method} DISPID={self.dispatch_ids[key]}",
                file=sys.stderr,
                flush=True,
            )
        result = obj.Invoke(self.dispatch_ids[key], 0, info["invoke_kind"], True, *args)
        if os.environ.get("CHEMCAD_MCP_DEBUG") == "1":
            print(f"COM returned {surface}.{method}", file=sys.stderr, flush=True)
        return result

    def require_simulation(self, write=False):
        if self.path is None:
            raise ValueError("Open a simulation first")
        if write and self.read_only:
            raise ValueError(
                "This simulation is read-only. Open a writable copy using copy_to."
            )

    def open_simulation(self, path, read_only=True, copy_to=None):
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in (".ccsim", ".ccx"):
            raise ValueError("Expected an existing .ccsim or .ccx simulation file")
        if copy_to:
            destination = Path(copy_to).expanduser().resolve()
            if destination.suffix.lower() != source.suffix.lower():
                raise ValueError(
                    "copy_to must use the same file extension as the source"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidental overwrite, including a racing writer.
            with source.open("rb") as src, destination.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            source = destination
        self.connect()
        self.children.clear()
        self.dispatch_ids.clear()
        result = self.call("server", "LoadSim", str(source), int(read_only))
        if result != 0:
            self.path = None
            self.read_only = True
            raise RuntimeError(f"LoadSim failed with CHEMCAD code {result}")
        self.path = str(source)
        self.read_only = read_only
        return self.status()

    def close_simulation(self):
        self.require_simulation()
        code = self.call("server", "CloseSimulation")
        if code != 0:
            raise RuntimeError(f"CloseSimulation failed with CHEMCAD code {code}")
        self.children.clear()
        self.path = None
        self.read_only = True
        return self.status()

    def save_simulation(self):
        self.require_simulation(write=True)
        code = self.call("server", "SaveSimulation")
        if code != 0:
            raise RuntimeError(f"SaveSimulation failed with CHEMCAD code {code}")
        return {"saved": True, "path": self.path}

    def ids(self, method, count, *args):
        if count == 0:
            return []
        array = self.array([0] * count, self.com.VT_I2)
        returned = self.call("flowsheet", method, *args, array)
        if returned != count:
            raise RuntimeError(f"{method} returned {returned} IDs; expected {count}")
        return list(array.value[1 : count + 1])

    def components(self):
        self.require_simulation()
        count = self.call("streams", "GetNoOfComponents")
        return [
            {
                "position": pos,
                "id": self.call("streams", "GetComponentIDByPosBaseOne", pos),
                "name": self.call("streams", "GetComponentNameByPosBaseOne", pos),
            }
            for pos in range(1, count + 1)
        ]

    def summary(self):
        self.require_simulation()
        stream_ids = self.ids(
            "GetAllStreamIDs", self.call("flowsheet", "GetNoOfStreams")
        )
        unit_ids = self.ids("GetAllUnitOpIDs", self.call("flowsheet", "GetNoOfUnitOps"))
        streams, unitops = [], []
        for stream_id in stream_ids:
            source, target = self.ref(self.com.VT_I2), self.ref(self.com.VT_I2)
            count = self.call(
                "flowsheet", "GetSourceAndTargetForStream", stream_id, source, target
            )
            if not 0 <= count <= 2:
                raise RuntimeError(
                    f"Unable to read endpoints for stream {stream_id}: {count}"
                )
            streams.append(
                {
                    "id": stream_id,
                    "label": self.call("streams", "GetStreamLabelByID", stream_id),
                    "source_unitop": source.value,
                    "target_unitop": target.value,
                }
            )
        for unit_id in unit_ids:
            inlet_count, outlet_count = (
                self.ref(self.com.VT_I2),
                self.ref(self.com.VT_I2),
            )
            self.call(
                "flowsheet",
                "GetStreamCountsToUnitOp",
                unit_id,
                inlet_count,
                outlet_count,
            )
            category = self.ref(self.com.VT_BSTR, "")
            self.call("unitops", "GetUnitOpCategoryByID", unit_id, category)
            unitops.append(
                {
                    "id": unit_id,
                    "label": self.call("unitops", "GetUnitOpLabelByID", unit_id),
                    "category": category.value,
                    "inlets": self.ids(
                        "GetInletStreamIDsToUnitOp", inlet_count.value, unit_id
                    ),
                    "outlets": self.ids(
                        "GetOutletStreamIDsToUnitOp", outlet_count.value, unit_id
                    ),
                    "error_code": self.call(
                        "unitops", "GetUnitOpRunTimeErrorCode", unit_id
                    ),
                    "error_message": self.call(
                        "unitops", "GetUnitOpRunTimeErrorStr", unit_id
                    ),
                }
            )
        return {
            "simulation": self.status(),
            "components": self.components(),
            "streams": streams,
            "unitops": unitops,
        }

    def valid_id(self, object_id, unitop=False):
        self.require_simulation()
        method, count_method = (
            ("GetAllUnitOpIDs", "GetNoOfUnitOps")
            if unitop
            else ("GetAllStreamIDs", "GetNoOfStreams")
        )
        if object_id not in self.ids(method, self.call("flowsheet", count_method)):
            raise ValueError(
                f"Unknown {'unitop' if unitop else 'stream'} ID: {object_id}"
            )

    def read_stream(self, stream_id, units="si"):
        self.valid_id(stream_id)
        count = self.call("streams", "GetNoOfComponents")
        scalar = [self.ref(self.com.VT_R4, 0.0) for _ in range(4)]
        rates = self.array([0.0] * count)
        returned = self.call("streams", "GetStreamByID", stream_id, *scalar, rates)
        if returned != count:
            raise RuntimeError(
                f"GetStreamByID returned {returned}; expected {count} components"
            )
        temp, pres, vapor, enthalpy = [v.value for v in scalar]
        comp_rates = list(rates.value[1 : count + 1])
        if units == "si":
            temp, pres, enthalpy = temp / 1.8, pres * PSIA_TO_PA, enthalpy * BTU_HR_TO_W
            comp_rates = [v * LBMOL_TO_KMOL for v in comp_rates]
            labels = {
                "temperature": "K",
                "pressure": "Pa (absolute)",
                "enthalpy_rate": "W",
                "component_flow": "kmol/h",
            }
        elif units == "internal":
            labels = {
                "temperature": "degR",
                "pressure": "psia",
                "enthalpy_rate": "Btu/h",
                "component_flow": "lbmol/h",
            }
        else:
            raise ValueError("units must be si or internal")
        return {
            "id": stream_id,
            "label": self.call("streams", "GetStreamLabelByID", stream_id),
            "temperature": temp,
            "pressure": pres,
            "vapor_mole_fraction": vapor,
            "enthalpy_rate": enthalpy,
            "units": labels,
            "components": [
                {**comp, "flow": flow}
                for comp, flow in zip(self.components(), comp_rates)
            ],
        }

    def write_stream(
        self,
        stream_id,
        temperature_k,
        pressure_pa,
        component_flows_kmol_h,
        vapor_mole_fraction=0.0,
        enthalpy_w=0.0,
        reflash=True,
    ):
        self.require_simulation(write=True)
        self.valid_id(stream_id)
        count = self.call("streams", "GetNoOfComponents")
        if len(component_flows_kmol_h) != count:
            raise ValueError(f"Provide {count} component flows in components() order")
        if (
            finite(temperature_k, "temperature_k") <= 0
            or finite(pressure_pa, "pressure_pa") <= 0
        ):
            raise ValueError("Absolute temperature and pressure must be positive")
        if not 0 <= finite(vapor_mole_fraction, "vapor_mole_fraction") <= 1:
            raise ValueError("vapor_mole_fraction must be between 0 and 1")
        finite(enthalpy_w, "enthalpy_w")
        if any(finite(v, "component flow") < 0 for v in component_flows_kmol_h):
            raise ValueError("Component flows must be nonnegative")
        rates = self.array([v / LBMOL_TO_KMOL for v in component_flows_kmol_h])
        returned = self.call(
            "streams",
            "PutStreamByID",
            stream_id,
            temperature_k * 1.8,
            pressure_pa / PSIA_TO_PA,
            vapor_mole_fraction,
            enthalpy_w / BTU_HR_TO_W,
            rates,
        )
        if returned != count:
            raise RuntimeError(f"PutStreamByID returned {returned}; expected {count}")
        if reflash:
            code = self.call("streams", "ReflashStream", stream_id)
            if code != 0:
                raise RuntimeError(
                    f"Stream was updated, but ReflashStream failed with code {code}; changes are unsaved"
                )
        return self.read_stream(stream_id)

    def unitop_parameter(self, unitop_id, parameter_id, user_units=True, value=None):
        self.valid_id(unitop_id, unitop=True)
        dimension = self.call("unitops", "GetUnitOpSpecArrayDimension")
        if not 1 <= parameter_id <= dimension:
            raise ValueError(f"parameter_id must be between 1 and {dimension}")
        suffix = "InCurUserUnit" if user_units else ""
        if value is not None:
            self.require_simulation(write=True)
            code = self.call(
                "unitops",
                "PutUnitOpPar" + suffix,
                unitop_id,
                parameter_id,
                finite(value, "value"),
            )
            if code != 1:
                raise RuntimeError(f"PutUnitOpPar failed with code {code}")
        holder = self.ref(self.com.VT_R4, 0.0)
        code = self.call(
            "unitops", "GetUnitOpPar" + suffix, holder, parameter_id, unitop_id
        )
        if code != 1:
            raise RuntimeError(f"GetUnitOpPar failed with code {code}")
        return {
            "unitop_id": unitop_id,
            "parameter_id": parameter_id,
            "value": holder.value,
            "units": "current flowsheet units"
            if user_units
            else "CHEMCAD internal units",
        }

    def run_simulation(self, mode="steady_state", unitop_ids=None):
        self.require_simulation(write=True)
        actual_mode = self.call("server", "GetSimulationMode")
        if mode == "steady_state":
            if actual_mode != 0:
                raise ValueError("The loaded simulation is dynamic")
            if unitop_ids:
                for unit_id in unitop_ids:
                    self.valid_id(unit_id, unitop=True)
                code = self.call(
                    "server",
                    "SSRunSelectedUnits",
                    self.array(unitop_ids, self.com.VT_I2),
                )
            else:
                code = self.call("server", "SSRunAllUnits")
        elif mode in ("dynamic_step", "dynamic_all"):
            if actual_mode != 1 or unitop_ids:
                raise ValueError(
                    "Dynamic runs require a dynamic simulation and no unitop_ids"
                )
            code = self.call(
                "server",
                "DynamicRunStep" if mode == "dynamic_step" else "DynamicRunAllSteps",
            )
        else:
            raise ValueError("Unknown simulation mode")
        result = {
            "success": code == 0,
            "code": code,
            "messages": self.call("server", "ShowRunTimeMessages"),
        }
        if actual_mode == 1:
            result["time_minutes"] = self.call("server", "GetDynamicTimeInMinute")
        return result

    def flash_tp(self, temperature_k, pressure_pa, component_flows_kmol_h):
        self.require_simulation()
        if (
            finite(temperature_k, "temperature_k") <= 0
            or finite(pressure_pa, "pressure_pa") <= 0
        ):
            raise ValueError("Absolute temperature and pressure must be positive")
        count = self.call("streams", "GetNoOfComponents")
        if len(component_flows_kmol_h) != count or any(
            finite(v, "flow") < 0 for v in component_flows_kmol_h
        ):
            raise ValueError(f"Provide {count} nonnegative component flows")
        temp, pres = temperature_k * 1.8, pressure_pa / PSIA_TO_PA
        code = self.call(
            "flash",
            "DefineFeedStream",
            temp,
            pres,
            0.0,
            self.array([v / LBMOL_TO_KMOL for v in component_flows_kmol_h]),
        )
        if code != count:
            raise RuntimeError(f"DefineFeedStream returned {code}; expected {count}")
        code = self.call("flash", "CalculateTPFlash", temp, pres)
        if code != 0:
            raise RuntimeError(f"CalculateTPFlash failed with code {code}")
        phases = {}
        phase_rates = {}
        components = self.components()
        for phase, getter in (
            ("liquid", "GetLiquidStream"),
            ("vapor", "GetVaporStream"),
        ):
            scalars = [self.ref(self.com.VT_R4, 0.0) for _ in range(4)]
            rates = self.array([0.0] * count)
            returned = self.call("flash", getter, *scalars, rates)
            if returned != count:
                raise RuntimeError(f"{getter} returned {returned}; expected {count}")
            phase_rates[phase] = list(rates.value[1 : count + 1])
            phases[phase] = {
                "temperature_k": scalars[0].value / 1.8,
                "pressure_pa": scalars[1].value * PSIA_TO_PA,
                "enthalpy_w": scalars[2].value * BTU_HR_TO_W,
                "flow_kmol_h": scalars[3].value * LBMOL_TO_KMOL,
                "components": [
                    {**component, "flow_kmol_h": rate * LBMOL_TO_KMOL}
                    for component, rate in zip(components, rates.value[1 : count + 1])
                ],
            }
        # TP flash enthalpy outputs remain at the supplied feed value. Calculate
        # phase enthalpies explicitly using the model's separate enthalpy API.
        for phase, data in phases.items():
            if data["flow_kmol_h"] == 0:
                data["enthalpy_w"] = 0.0
                continue
            defined = self.call(
                "enthalpy", "DefineStream", temp, pres, self.array(phase_rates[phase])
            )
            if defined != count:
                raise RuntimeError(
                    f"Enthalpy DefineStream returned {defined}; expected {count}"
                )
            enthalpy = self.ref(self.com.VT_R4, 0.0)
            calculated = self.call(
                "enthalpy",
                "CalculateLiquidEnthalpy"
                if phase == "liquid"
                else "CalculateVaporEnthalpy",
                enthalpy,
            )
            if calculated != 1:
                raise RuntimeError(f"CHEMCAD could not calculate {phase} enthalpy")
            data["enthalpy_w"] = enthalpy.value * BTU_HR_TO_W
        return {
            "temperature_k": self.call("flash", "GetTemperature") / 1.8,
            "pressure_pa": self.call("flash", "GetPressure") * PSIA_TO_PA,
            "vapor_mole_fraction": self.call("flash", "GetMoleVaporFraction"),
            "enthalpy_w": sum(phase["enthalpy_w"] for phase in phases.values()),
            **phases,
        }

    def invoke(self, surface, method, arguments=None):
        info = describe_api(surface, method)
        # File lifecycle is routed through tools which keep path/read-only state consistent.
        if surface == "server" and method in {
            "LoadSim",
            "LoadJob",
            "SwitchWorkDir",
            "SaveSimulation",
            "CloseSimulation",
        }:
            raise ValueError(
                "Use the dedicated simulation lifecycle tools for this method"
            )
        scratch = {
            "flash",
            "k_values",
            "enthalpy",
            "stream_properties",
            "stream_units",
            "unitop_units",
            "engineering_units",
        }
        if surface not in scratch and not method.lower().startswith(
            ("get", "show", "pid")
        ):
            self.require_simulation(write=True)
        supplied = arguments or {}
        parameters = info["parameters"]
        unknown = set(supplied) - {p["name"] for p in parameters}
        if unknown:
            raise ValueError(f"Unknown arguments: {sorted(unknown)}")
        args, references = [], {}
        types = {
            "i2": self.com.VT_I2,
            "i4": self.com.VT_I4,
            "r4": self.com.VT_R4,
            "r8": self.com.VT_R8,
            "bstr": self.com.VT_BSTR,
            "variant": self.com.VT_VARIANT,
            "array_i2": self.com.VT_ARRAY | self.com.VT_I2,
            "array_i4": self.com.VT_ARRAY | self.com.VT_I4,
            "array_r4": self.com.VT_ARRAY | self.com.VT_R4,
            "array_r8": self.com.VT_ARRAY | self.com.VT_R8,
            "array_bstr": self.com.VT_ARRAY | self.com.VT_BSTR,
        }
        for param in parameters:
            name, vartype = param["name"], param["vartype"]
            is_ref = bool(vartype & self.com.VT_BYREF)
            base = vartype & ~self.com.VT_BYREF
            if name not in supplied and not (param["flags"] == 2):
                raise ValueError(
                    f"Missing argument: {name}; pass an initial value for legacy reference parameters"
                )
            value = supplied.get(name, "" if base == self.com.VT_BSTR else 0)
            if isinstance(value, dict) and "type" in value:
                type_name = value["type"]
                if type_name not in types:
                    raise ValueError(f"Unknown COM type: {type_name}")
                base = types[type_name]
                is_ref = bool(value.get("byref", is_ref))
                value = value.get("value", [])
            if isinstance(value, list):
                if not base & self.com.VT_ARRAY:
                    raise ValueError(f"Use a typed array descriptor for {name}")
                if len(value) > 65536:
                    raise ValueError("Array exceeds 65536 elements")
            if is_ref:
                arg = self.ref(base, value)
                references[name] = arg
            elif base != self.com.VT_VARIANT:
                arg = self.variant(base, value)
            else:
                arg = value
            args.append(arg)
        result = self.call(surface, method, *args)
        return {
            "return_value": json_value(result),
            "references": {name: json_value(v.value) for name, v in references.items()},
        }


OPERATIONS = {
    "connect",
    "status",
    "disconnect",
    "open_simulation",
    "close_simulation",
    "save_simulation",
    "components",
    "summary",
    "read_stream",
    "write_stream",
    "unitop_parameter",
    "run_simulation",
    "flash_tp",
    "invoke",
}


def main():
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    automation = Automation()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if request["operation"] not in OPERATIONS:
                    raise ValueError("Unknown operation")
                result = getattr(automation, request["operation"])(
                    **request.get("arguments", {})
                )
                response = {"ok": True, "result": json_value(result)}
            except Exception as error:
                if (
                    not isinstance(error, (ValueError, FileExistsError))
                    or os.environ.get("CHEMCAD_MCP_DEBUG") == "1"
                ):
                    traceback.print_exc(file=sys.stderr)
                response = {
                    "ok": False,
                    "error": str(error),
                    "error_type": type(error).__name__,
                }
                if hasattr(error, "hresult"):
                    response["hresult"] = f"0x{error.hresult & 0xFFFFFFFF:08X}"
            print(json.dumps(response, allow_nan=False), flush=True)
            pythoncom.PumpWaitingMessages()
    finally:
        automation.disconnect()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
