"""Probe XML model construction on disposable copies; no source file changes."""

import argparse
import asyncio
import copy
import json
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from chemcad_mcp.bridge import WorkerBridge


def create_variants(source: Path, directory: Path):
    with zipfile.ZipFile(source) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    master = next(
        info.filename
        for info, data in entries
        if info.filename.lower().endswith(".xml")
        and "_last." not in info.filename.lower()
        and b"<CHEMCAD " in data
    )
    tree = ET.fromstring(dict((info.filename, data) for info, data in entries)[master])
    variants = []
    for name in ("extra_mixer", "extra_mixer_no_drawing", "extra_component"):
        root = copy.deepcopy(tree)
        if name.startswith("extra_mixer"):
            equipment = root.find("Equipment")
            streams = root.find("Streams")
            mixer = copy.deepcopy(
                next(unit for unit in equipment if unit.get("ename") == "MIXE")
            )
            mixer.set("ide", "9")
            mixer.set("uname", "Probe mixer")
            ports = mixer.find("ioe")
            ports.clear()
            for index, value in enumerate((9, 10, -11)):
                ET.SubElement(ports, "Item", key=str(index), data=str(value))
            equipment.append(mixer)
            terminal = next(stream for stream in streams if stream.get("ID") == "10")
            terminal.find("issdi").set("issdi2", "9")
            output = copy.deepcopy(terminal)
            output.set("ID", "11")
            output.set("sname", "Probe output")
            output.find("issdi").attrib.update(issdi0="11", issdi1="9", issdi2="0")
            streams.append(output)
        else:
            root.find("TLK/GeneralInfo").set("NumberOfComponents", "9")
            ET.SubElement(root.find("TLK/ComponentIDs"), "Component", ID="3")
            for stream in root.find("Streams"):
                components = stream.find("Components")
                zero = next(
                    item.get("data") for item in components if item.get("key") == "4"
                )
                ET.SubElement(components, "item", key="8", data=zero)
        path = directory / f"{name}.ccsim"
        with zipfile.ZipFile(path, "x") as output:
            for info, data in entries:
                if name.endswith("no_drawing") and info.filename.lower().endswith(
                    ".flwshtcc7"
                ):
                    continue
                if info.filename == master:
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                output.writestr(info, data)
        variants.append((name, path))
    return variants


async def probe(source: Path):
    directory = Path(tempfile.mkdtemp(prefix="archive-build-", dir=Path("work")))
    variants = create_variants(source, directory)
    bridge = WorkerBridge(timeout=120)
    results = []
    try:
        for name, path in [("base", source), *variants]:
            print(f"Loading {name}", flush=True)
            try:
                await bridge.request(
                    "open_simulation", path=str(path.resolve()), read_only=True
                )
                summary = await bridge.request("summary")
                result = {
                    "variant": name,
                    "components": summary["components"],
                    "unitops": [
                        {
                            key: unit[key]
                            for key in ("id", "label", "category", "inlets", "outlets")
                        }
                        for unit in summary["unitops"]
                    ],
                    "streams": summary["streams"],
                }
                print(json.dumps(result), flush=True)
                results.append(result)
                await bridge.request("close_simulation")
            except Exception as error:
                print(f"{name}: {error}", flush=True)
                results.append({"variant": name, "error": str(error)})
    finally:
        if bridge.process is not None:
            await bridge.request("disconnect")
        await bridge.close()
    (directory / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"Report: {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    asyncio.run(probe(parser.parse_args().source))
