"""Experimental logical-model construction using licensed .ccsim templates.

Never decode opaque numeric fields; clone valid prototypes and configure through
COM. The inherited binary drawing is NOT regenerated. No vendor files are shipped.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .installation import examples_directory
from .windows import ensure_windows_environment

LIMIT = 512 * 1024 * 1024
INDEPENDENT_CATEGORIES = {"COMP", "EXPN", "HTXR", "MIXE", "PUMP", "VALV"}
DRAWING_WARNING = (
    "Experimental calculation topology: the inherited CHEMCAD GUI drawing is not "
    "regenerated and may show different equipment/connections. Configure all new "
    "equipment, run, inspect errors/balances, save and reopen before trusting results."
)


class ModelArchive:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve(strict=True)
        if self.path.suffix.lower() != ".ccsim":
            raise ValueError("Archive construction requires a .ccsim ZIP file")
        with zipfile.ZipFile(self.path) as archive:
            infos = archive.infolist()
            if len({i.filename for i in infos}) != len(infos):
                raise ValueError("Duplicate archive entries")
            if sum(i.file_size for i in infos) > LIMIT:
                raise ValueError("Simulation archive exceeds 512 MiB uncompressed")
            self.entries = [(info, archive.read(info)) for info in infos]
        self.master = None
        for info, data in self.entries:
            if (
                info.filename.lower().endswith(".xml")
                and "_last." not in info.filename.lower()
            ):
                if b"<CHEMCAD " in data:
                    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                        raise ValueError("XML entities are not supported")
                    if self.master is not None:
                        raise ValueError("Ambiguous primary CHEMCAD XML")
                    self.master, self.root = info.filename, ET.fromstring(data)
        if self.master is None:
            raise ValueError("No primary CHEMCAD XML in archive")
        if self.root.find("Equipment") is None or self.root.find("Streams") is None:
            raise ValueError("Missing logical equipment/stream sections")
        self.component_ids = [
            int(c.get("ID")) for c in self.root.findall("TLK/ComponentIDs/Component")
        ]

    def data(self, suffix: str) -> tuple[str, bytes]:
        name = str(Path(self.master).with_suffix(suffix)).replace("\\", "/")
        matches = [
            (i.filename, data)
            for i, data in self.entries
            if i.filename.replace("\\", "/") == name
        ]
        if len(matches) != 1:
            raise ValueError(f"Missing primary {suffix} entry")
        return matches[0]

    def describe(self) -> dict:
        return {
            "path": str(self.path),
            "component_ids": self.component_ids,
            "unitops": [
                {
                    "id": int(e.get("ide")),
                    "category": e.get("ename"),
                    "label": e.get("uname", ""),
                }
                for e in self.root.findall("Equipment/UnitOp")
            ],
            "streams": [
                {
                    "id": int(s.get("ID")),
                    "label": s.get("sname", ""),
                    "source_unitop": int(s.find("issdi").get("issdi1")),
                    "target_unitop": int(s.find("issdi").get("issdi2")),
                }
                for s in self.root.findall("Streams/Stream")
            ],
        }


def list_templates(
    directory: str | None = None,
    query: str = "",
    required_component_ids: list[int] | None = None,
    limit: int = 30,
) -> dict:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be 1..200")
    directory = (
        Path(directory).resolve(strict=True) if directory else examples_directory()
    )
    if not directory.is_dir():
        raise ValueError("Expected an examples directory")
    results, errors = [], 0
    for path in sorted(directory.rglob("*.ccsim")):
        if query.casefold() not in str(path.relative_to(directory)).casefold():
            continue
        try:
            model = ModelArchive(path)
            if not set(required_component_ids or []).issubset(model.component_ids):
                continue
            desc = model.describe()
            results.append(
                {
                    "path": str(path),
                    "name": path.stem,
                    "component_ids": model.component_ids,
                    "categories": sorted({u["category"] for u in desc["unitops"]}),
                    "unitop_count": len(desc["unitops"]),
                    "stream_count": len(desc["streams"]),
                }
            )
        except (ValueError, OSError, zipfile.BadZipFile, ET.ParseError):
            errors += 1
        if len(results) == limit:
            break
    return {"templates": results, "skipped_unreadable": errors, "limit": limit}


def _extend_gibbs_element_matrix(model, imported, grid_data=None) -> dict[str, bytes]:
    """Extend the supported plaintext Gibbs matrix using licensed ATOMS rows.

    Only existing element columns are supported. Never silently leave imported
    fuels outside the atom balance or guess new element-reference conventions.
    """
    name, matrix = model.data(".400")
    lines = [
        line.strip() for line in matrix.decode("cp1252").splitlines() if line.strip()
    ]
    if len(lines) != len(model.component_ids) + 3:
        raise ValueError("Unsupported Gibbs element matrix layout")
    header, numbers, reference = [line.split() for line in lines[:3]]
    count = len(numbers)
    if len(header) != count + 1 or len(reference) != count:
        raise ValueError("Unsupported Gibbs element matrix header")
    atomic_numbers = [int(v) for v in numbers]
    if len(set(atomic_numbers)) != count:
        raise ValueError("Duplicate element columns in Gibbs matrix")
    for cid, line in zip(model.component_ids, lines[3:]):
        cells = line.split()
        if len(cells) != count + 1 or int(cells[0]) != cid:
            raise ValueError("Gibbs element matrix does not match selected components")
    for item in imported:
        atoms = item.get("atoms")
        if not atoms:
            raise ValueError(
                f"Missing licensed element composition for component {item['id']}"
            )
        row = [0.0] * count
        seen = set()
        for atom in atoms:
            number, value = atom["atomic_number"], float(atom["count"])
            if number not in atomic_numbers:
                raise ValueError(
                    f"Imported component {item['id']} introduces unsupported element {number}; "
                    "use a template with this element already defined in its Gibbs matrix"
                )
            if number in seen or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid licensed element composition")
            seen.add(number)
            row[atomic_numbers.index(number)] = value
        lines.append(f"{item['id']} " + " ".join(f"{v:g}" for v in row))
    if grid_data is None:
        matches = [
            (i.filename, data)
            for i, data in model.entries
            if i.filename.upper() == "$ATOM.GRD"
        ]
        if len(matches) != 1:
            raise ValueError("Missing/ambiguous Gibbs element matrix grid")
        grid_data = matches[0]
    grid_name, grid = grid_data
    grid_lines = [
        line.strip() for line in grid.decode("cp1252").splitlines() if line.strip()
    ]
    marker = f"ROW {len(model.component_ids)}"
    row_indices = [
        i for i, line in enumerate(grid_lines) if line.split() == marker.split()
    ]
    if len(row_indices) != 1:
        raise ValueError("Unsupported Gibbs element grid row layout")
    row_index = row_indices[0]
    old_count = len(model.component_ids)
    tail = grid_lines[row_index + old_count + 1 :]
    if tail[:2] != ["READ-ONLY_CELLS 0", f"READ-ONLY_ROWS {old_count}"]:
        raise ValueError("Unsupported Gibbs element grid protection layout")
    total = old_count + len(imported)
    new_grid = (
        grid_lines[:row_index]
        + [f"ROW {total}"]
        + grid_lines[row_index + 1 : row_index + old_count + 1]
    )
    new_grid += [json.dumps(item["name"], ensure_ascii=False) for item in imported]
    new_grid += ["READ-ONLY_CELLS 0", f"READ-ONLY_ROWS {total}"] + [
        str(i) for i in range(total)
    ]
    return {
        name: ("\n".join(lines) + "\n").encode("cp1252"),
        grid_name: ("\n".join(new_grid) + "\n").encode("cp1252"),
    }


def _object_id(value, name: str, zero=False) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (0 if zero else 1) <= value <= 32767
    ):
        raise ValueError(f"{name} must be an integer in {'0' if zero else '1'}..32767")
    return value


def _merge_properties(
    model: ModelArchive, imports: list[dict]
) -> tuple[str, bytes, list[dict]]:
    if os.name != "nt":
        raise RuntimeError("Component-property import requires Windows and 32-bit Jet")
    ensure_windows_environment()
    name, database = model.data(".ppdb")
    with tempfile.TemporaryDirectory(prefix="chemcad-properties-") as temporary:
        directory = Path(temporary)
        destination = directory / "model.ppdb"
        destination.write_bytes(database)
        jobs = []
        for index, item in enumerate(imports):
            donor = ModelArchive(item["donor_path"])
            if item["id"] not in donor.component_ids:
                raise ValueError(
                    f"Component {item['id']} not selected in donor archive"
                )
            donor_path = directory / f"donor-{index}.ppdb"
            donor_path.write_bytes(donor.data(".ppdb")[1])
            jobs.append({"id": item["id"], "donor": str(donor_path)})
        job_path = directory / "job.json"
        job_path.write_text(
            json.dumps({"destination": str(destination), "imports": jobs}),
            encoding="utf-8",
        )
        powershell = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "SysWOW64/WindowsPowerShell/v1.0/powershell.exe"
        )
        if not powershell.is_file():
            raise RuntimeError(
                "32-bit Windows PowerShell / Jet provider required for component import"
            )
        result = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_name("merge_properties.ps1")),
                "-JobPath",
                str(job_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Property import failed; no model created: {result.stderr.strip()}"
            )
        return name, destination.read_bytes(), json.loads(result.stdout)["components"]


def create_model(
    template_path: str,
    output_path: str,
    unitops: list[dict] | None = None,
    connections: list[dict] | None = None,
    component_imports: list[dict] | None = None,
    replace_topology: bool = False,
    acknowledge_stale_drawing: bool = False,
) -> dict:
    """Write a NEW archive; never mutate the template or an opened model.

    Unit declarations: id, prototype_id, optional prototype_path/label, inlets,
    outlets (ordered stream IDs). Connections: id, source_unitop, target_unitop,
    optional label/prototype_stream_id. Existing stream endpoints can be changed.
    Component imports append IDs using donor_path; no reordering/deletion/BIP import.
    """
    model = ModelArchive(template_path)
    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.lower() != ".ccsim":
        raise ValueError("output_path must end in .ccsim")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    modified = bool(unitops or connections or component_imports or replace_topology)
    if modified and not acknowledge_stale_drawing:
        raise ValueError("Set acknowledge_stale_drawing=true: " + DRAWING_WARNING)
    if not modified:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with model.path.open("rb") as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output)
        return {"path": str(destination), "copied": True, "warnings": []}
    root = copy.deepcopy(model.root)
    equipment, streams = root.find("Equipment"), root.find("Streams")
    stream_prototypes = {
        int(s.get("ID")): s for s in model.root.findall("Streams/Stream")
    }
    if replace_topology:
        equipment.clear()
        streams.clear()
    units = {int(e.get("ide")): e for e in equipment}
    declared_ports = {}
    for item in unitops or []:
        uid = _object_id(item["id"], "unitop id")
        if uid in units:
            raise ValueError(f"Duplicate unitop ID: {uid}")
        donor = (
            ModelArchive(item["prototype_path"])
            if item.get("prototype_path")
            else model
        )
        try:
            prototype = next(
                e
                for e in donor.root.findall("Equipment/UnitOp")
                if int(e.get("ide")) == item["prototype_id"]
            )
        except StopIteration:
            raise ValueError(
                f"Unknown equipment prototype: {item['prototype_id']}"
            ) from None
        if (
            donor.component_ids != model.component_ids
            and prototype.get("ename") not in INDEPENDENT_CATEGORIES
        ):
            raise ValueError(
                "Cross-component-list prototypes are restricted to COMP/EXPN/HTXR/MIXE/PUMP/VALV"
            )
        unit = copy.deepcopy(prototype)
        unit.set("ide", str(uid))
        unit.set("uname", str(item.get("label", f"{prototype.get('ename')} {uid}")))
        inlets = [_object_id(s, "inlet stream") for s in item["inlets"]]
        outlets = [_object_id(s, "outlet stream") for s in item["outlets"]]
        if (
            not inlets
            or not outlets
            or len(set(inlets + outlets)) != len(inlets + outlets)
        ):
            raise ValueError(
                "New equipment needs distinct ordered inlet and outlet streams"
            )
        declared_ports[uid] = (inlets, outlets)
        units[uid] = unit
        equipment.append(unit)
    stream_map = {int(s.get("ID")): s for s in streams}
    for item in connections or []:
        sid = _object_id(item["id"], "stream id")
        source = _object_id(item["source_unitop"], "source unitop", zero=True)
        target = _object_id(item["target_unitop"], "target unitop", zero=True)
        if source == target or any(u and u not in units for u in (source, target)):
            raise ValueError(f"Invalid endpoints for stream {sid}")
        if sid not in stream_map:
            prototype_id = item.get(
                "prototype_stream_id", next(iter(stream_prototypes), None)
            )
            if prototype_id not in stream_prototypes:
                raise ValueError("No valid stream prototype")
            stream_map[sid] = copy.deepcopy(stream_prototypes[prototype_id])
            streams.append(stream_map[sid])
        stream = stream_map[sid]
        stream.set("ID", str(sid))
        stream.set("sname", str(item.get("label", stream.get("sname", ""))))
        stream.find("issdi").attrib.update(
            issdi0=str(sid), issdi1=str(source), issdi2=str(target)
        )
    for uid, unit in units.items():
        inlets = [
            sid
            for sid, s in stream_map.items()
            if int(s.find("issdi").get("issdi2")) == uid
        ]
        outlets = [
            sid
            for sid, s in stream_map.items()
            if int(s.find("issdi").get("issdi1")) == uid
        ]
        if uid in declared_ports:
            ordered_in, ordered_out = declared_ports[uid]
            if set(inlets) != set(ordered_in) or set(outlets) != set(ordered_out):
                raise ValueError(
                    f"Declared ports disagree with stream endpoints for unitop {uid}"
                )
            inlets, outlets = ordered_in, ordered_out
        else:
            old = [int(i.get("data")) for i in unit.find("ioe")][1:]
            inlets.sort(
                key=lambda sid: old.index(sid) if sid in old else len(old) + sid
            )
            outlets.sort(
                key=lambda sid: old.index(-sid) if -sid in old else len(old) + sid
            )
        ports = unit.find("ioe")
        ports.clear()
        for index, value in enumerate([uid, *inlets, *[-s for s in outlets]]):
            ET.SubElement(ports, "Item", key=str(index), data=str(value))
    replacements, imported = {}, []
    seen = set(model.component_ids)
    for item in component_imports or []:
        cid = _object_id(item["id"], "component id")
        if cid >= 5000 or cid in seen:
            raise ValueError(
                "Import unique ordinary databank IDs below 5000, not existing/custom components"
            )
        seen.add(cid)
    for sid, stream in stream_map.items():
        endpoints = stream.find("issdi")
        source, target = int(endpoints.get("issdi1")), int(endpoints.get("issdi2"))
        if source == target or any(u and u not in units for u in (source, target)):
            raise ValueError(f"Invalid final endpoints for stream {sid}")
    if not units or not stream_map:
        raise ValueError("Construct a nonempty model with equipment and streams")
    if component_imports:
        zero_index = component_imports[0].get("zero_flow_position")
        zero_stream_id = component_imports[0].get("zero_flow_stream_id")
        if (
            not isinstance(zero_index, int)
            or not 1 <= zero_index <= len(model.component_ids)
            or zero_stream_id not in stream_prototypes
        ):
            raise ValueError(
                "First import needs zero_flow_stream_id and zero_flow_position identifying a verified zero-flow value in the template"
            )
        zero = next(
            (
                e.get("data")
                for e in stream_prototypes[zero_stream_id].find("Components")
                if int(e.get("key")) == zero_index - 1
            ),
            None,
        )
        if zero is None:
            raise ValueError("Missing zero-flow prototype field")
        name, data, imported = _merge_properties(model, component_imports)
        replacements[name] = data
        if any(unit.get("ename") == "GIBS" for unit in equipment):
            replacements.update(_extend_gibbs_element_matrix(model, imported))
        # Use a zero-flow value proven by loading and reading the template in COM.
        # Opaque encoding is inherited, not interpreted or synthesized.
        for stream in streams:
            components = stream.find("Components")
            for index in range(len(component_imports)):
                ET.SubElement(
                    components,
                    "item",
                    key=str(len(model.component_ids) + index),
                    data=zero,
                )
        for item in component_imports:
            ET.SubElement(
                root.find("TLK/ComponentIDs"), "Component", ID=str(item["id"])
            )
        root.find("TLK/GeneralInfo").set("NumberOfComponents", str(len(seen)))
    replacements[model.master] = ET.tostring(
        root, encoding="utf-8", xml_declaration=True
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x") as output:
        for info, data in model.entries:
            output.writestr(info, replacements.get(info.filename, data))
    return {
        "path": str(destination),
        "unitop_count": len(units),
        "stream_count": len(stream_map),
        "imported_components": imported,
        "warnings": [
            DRAWING_WARNING,
            "Imported components have pure properties only; binary interactions, electrolyte and custom-component data are not merged.",
            "Gibbs imports extend the supported plaintext element matrix from licensed ATOMS rows; new element columns require a compatible template.",
        ]
        if imported
        else [DRAWING_WARNING],
    }
