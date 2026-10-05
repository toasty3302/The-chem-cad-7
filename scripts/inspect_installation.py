"""Read installed type libraries and PE metadata; never activate CHEMCAD."""

import json
from pathlib import Path

import pefile
import pythoncom
from win32com.client import build

INSTALL = Path(r"C:\Program Files (x86)\Chemstations\CHEMCAD NXT")


def main():
    library = pythoncom.LoadTypeLib(str(INSTALL / "chemcad.tlb"))
    report = {"library": library.GetDocumentation(-1), "types": []}
    api = {
        "library": library.GetDocumentation(-1)[0],
        "interfaces": {},
        "constants": {},
    }
    for index in range(library.GetTypeInfoCount()):
        info = library.GetTypeInfo(index)
        attr = info.GetTypeAttr()
        item = {
            "name": info.GetDocumentation(-1)[0],
            "documentation": info.GetDocumentation(-1),
            "attributes": tuple(attr),
            "functions": [],
            "variables": [],
        }
        for func_index in range(attr.cFuncs):
            desc = info.GetFuncDesc(func_index)
            item["functions"].append(
                {
                    "names": info.GetNames(desc[0]),
                    "documentation": info.GetDocumentation(desc[0]),
                    "descriptor": tuple(desc),
                }
            )
            names = info.GetNames(desc.memid)
            if desc.memid < 0x60000000:
                params = []
                for position, (vartype, flags, default) in enumerate(desc.args):
                    resolved, _, _ = build._ResolveType(vartype, info)
                    params.append(
                        {
                            "name": names[position + 1]
                            if position + 1 < len(names)
                            else f"arg{position}",
                            "vartype": resolved,
                            "flags": flags,
                        }
                    )
                result_type, _, _ = build._ResolveType(desc.rettype[0], info)
                api["interfaces"].setdefault(item["name"], {})[names[0]] = {
                    "dispid": desc.memid,
                    "invoke_kind": desc.invkind,
                    "return_type": result_type,
                    "parameters": params,
                }
        for var_index in range(attr.cVars):
            desc = info.GetVarDesc(var_index)
            item["variables"].append(
                {"name": info.GetDocumentation(desc[0])[0], "descriptor": tuple(desc)}
            )
            if attr.typekind == pythoncom.TKIND_ENUM:
                api["constants"][info.GetDocumentation(desc[0])[0]] = desc[1]
        report["types"].append(item)
    report["binaries"] = []
    for name in ("CCNXT.exe", "CcxDll.dll", "FlSht.dll", "SimData.dll", "CCXSim.dll"):
        path = INSTALL / name
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]]
        )
        exports = getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
        report["binaries"].append(
            {
                "name": name,
                "machine": hex(pe.FILE_HEADER.Machine),
                "exports": [
                    entry.name.decode("ascii", "replace")
                    if entry.name
                    else f"ordinal:{entry.ordinal}"
                    for entry in exports
                ],
            }
        )
    destination = (
        Path(__file__).resolve().parents[1] / "docs" / "installation-metadata.json"
    )
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    api_path = Path(__file__).resolve().parents[1] / "src" / "chemcad_mcp" / "api.json"
    api_path.write_text(json.dumps(api, indent=2, default=str), encoding="utf-8")
    print(library.GetDocumentation(-1))
    for item in report["types"]:
        print(
            item["name"],
            "attributes:",
            item["attributes"],
            "functions:",
            len(item["functions"]),
        )
    print("Report:", destination)


if __name__ == "__main__":
    main()
