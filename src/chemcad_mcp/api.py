"""Signatures recovered from the installed CHEMCAD type library."""

import json
from importlib.resources import files

API = json.loads(files("chemcad_mcp").joinpath("api.json").read_text(encoding="utf-8"))
SURFACES = {
    "server": ("ICHEMCADVBServer", None),
    "flowsheet": ("IFlowsheet", "GetFlowsheet"),
    "streams": ("IStreamInfo", "GetStreamInfo"),
    "unitops": ("IUnitOpInfo", "GetUnitOpInfo"),
    "flash": ("IFlash", "GetFlash"),
    "k_values": ("IKValues", "GetKValues"),
    "enthalpy": ("IEnthalpy", "GetEnthalpy"),
    "stream_properties": ("IStreamProperty", "GetStreamProperty"),
    "stream_units": ("IStreamUnitConversion", "GetStreamUnitConversion"),
    "unitop_units": ("IUnitOpSpecUnitConversion", "GetUnitOpSpecUnitConversion"),
    "engineering_units": ("IEngUnitConversion", "GetEngUnitConversion"),
    "component_properties": ("ICompPPData", "GetCompPPData"),
    "data_maps": ("IDataMap", "GetDataMaps"),
}


def describe_api(surface: str | None = None, method: str | None = None) -> dict:
    if surface is None:
        return {
            "surfaces": {
                name: list(API["interfaces"][info[0]])
                for name, info in SURFACES.items()
            },
            "constants": API["constants"],
            "notes": "Legacy arrays use a reserved zero element. Use typed arguments for VARIANT arrays. Native return codes are method-specific.",
        }
    if surface not in SURFACES:
        raise ValueError(f"Unknown surface: {surface}")
    methods = API["interfaces"][SURFACES[surface][0]]
    if method is not None:
        if method not in methods:
            raise ValueError(f"Unknown method: {surface}.{method}")
        return {"surface": surface, "method": method, **methods[method]}
    return {"surface": surface, "methods": methods}
