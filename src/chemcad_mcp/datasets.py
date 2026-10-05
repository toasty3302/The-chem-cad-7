"""Explicit, bounded XLSX inspection without external services or uploads."""

from __future__ import annotations

import math
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _xml(data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML entities are not supported")
    return ET.fromstring(data)


def read_xlsx_headers(path: str, sheet_names: list[str] | None = None) -> dict:
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("Expected an .xlsx file")
    with zipfile.ZipFile(source) as archive:

        def small_xml(name):
            if archive.getinfo(name).file_size > 2 * 1024 * 1024:
                raise ValueError("Workbook metadata exceeds 2 MiB")
            return _xml(archive.read(name))

        workbook = small_xml("xl/workbook.xml")
        relationships = {
            r.get("Id"): r for r in small_xml("xl/_rels/workbook.xml.rels")
        }
        sheets = workbook.findall(f"{S}sheets/{S}sheet")
        available = [s.get("name") for s in sheets]
        if sheet_names is not None and set(sheet_names) - set(available):
            raise ValueError(
                f"Unknown sheets: {sorted(set(sheet_names) - set(available))}"
            )
        results, required_strings = [], set()
        for sheet in sheets:
            if sheet_names is not None and sheet.get("name") not in sheet_names:
                continue
            rel = relationships[sheet.get(R + "id")]
            if rel.get("TargetMode") == "External":
                raise ValueError("External worksheets are not supported")
            target = rel.get("Target")
            target = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            if not target.startswith("xl/") or ".." in target.split("/"):
                raise ValueError("Invalid worksheet target")
            cells = []
            # Stop at row 1; no iteration over the actual measurement dataset.
            with archive.open(target) as stream:
                for event, row in ET.iterparse(stream, events=("end",)):
                    if row.tag != S + "row":
                        continue
                    if row.get("r", "1") == "1":
                        for cell in row.findall(S + "c"):
                            reference = cell.get("r", "")
                            if not re.fullmatch(r"[A-Z]+1", reference):
                                raise ValueError("Invalid first-row cell reference")
                            value = cell.findtext(S + "v")
                            kind = cell.get("t")
                            if kind == "s" and value is not None:
                                value = int(value)
                                if not 0 <= value <= 100000:
                                    raise ValueError(
                                        "Shared-string index exceeds header inspection bound"
                                    )
                                required_strings.add(value)
                            elif kind == "inlineStr":
                                value = "".join(
                                    t.text or "" for t in cell.findall(f"{S}is//{S}t")
                                )
                            cells.append(
                                {
                                    "cell": reference,
                                    "column": reference[:-1],
                                    "value": value,
                                    "_shared": kind == "s",
                                }
                            )
                    break
            results.append(
                {
                    "name": sheet.get("name"),
                    "state": sheet.get("state", "visible"),
                    "headers": cells,
                }
            )
        strings = {}
        if required_strings:
            with archive.open("xl/sharedStrings.xml") as stream:
                index = 0
                for event, item in ET.iterparse(stream, events=("end",)):
                    if item.tag == S + "si":
                        if index in required_strings:
                            strings[index] = "".join(
                                t.text or "" for t in item.iter(S + "t")
                            )
                        item.clear()
                        if len(strings) == len(required_strings):
                            break
                        index += 1
            if required_strings - set(strings):
                raise ValueError("Missing shared-string entries")
        for sheet in results:
            for cell in sheet["headers"]:
                if cell.pop("_shared") and cell["value"] is not None:
                    cell["value"] = strings[cell["value"]]
    return {
        "path": str(source),
        "row_read": 1,
        "available_sheets": available,
        "sheets": results,
        "warning": "Headers identify tags, not measured values or verified units. No measurement rows were inspected.",
    }


def read_xlsx_rows(
    path: str,
    sheet_name: str,
    start_row: int = 2,
    count: int = 30,
    columns: list[str] | None = None,
) -> dict:
    """Read an explicitly selected window; timestamps remain Excel serials/text."""
    if not 2 <= start_row <= 100000 or not 1 <= count <= 1000:
        raise ValueError("start_row must be 2..100000 and count must be 1..1000")
    if columns is not None and (
        not columns or any(not re.fullmatch(r"[A-Z]{1,3}", c) for c in columns)
    ):
        raise ValueError("columns must be Excel letters, e.g. A,D,H")
    headers = read_xlsx_headers(path, [sheet_name])["sheets"][0]["headers"]
    source = Path(path).expanduser().resolve(strict=True)
    rows, needed = [], set()
    with zipfile.ZipFile(source) as archive:
        workbook = _xml(archive.read("xl/workbook.xml"))
        sheet = next(
            s
            for s in workbook.findall(f"{S}sheets/{S}sheet")
            if s.get("name") == sheet_name
        )
        rels = _xml(archive.read("xl/_rels/workbook.xml.rels"))
        rel = next(r for r in rels if r.get("Id") == sheet.get(R + "id"))
        target = rel.get("Target")
        target = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        if rel.get("TargetMode") == "External" or not target.startswith("xl/"):
            raise ValueError("External/invalid sheet target")
        properties = workbook.find(S + "workbookPr")
        date1904 = properties is not None and properties.get("date1904") in {
            "1",
            "true",
        }
        with archive.open(target) as stream:
            for event, row in ET.iterparse(stream, events=("end",)):
                if row.tag != S + "row":
                    continue
                number = int(row.get("r"))
                if number >= start_row + count:
                    break
                if number >= start_row:
                    cells = {}
                    for cell in row.findall(S + "c"):
                        column = re.sub(r"\d+$", "", cell.get("r", ""))
                        if columns is not None and column not in columns:
                            continue
                        kind, value = cell.get("t"), cell.findtext(S + "v")
                        if kind == "s" and value is not None:
                            index = int(value)
                            if not 0 <= index <= 1000000:
                                raise ValueError("Shared-string index exceeds bound")
                            needed.add(index)
                            value = {"_shared": index}
                        elif kind == "inlineStr":
                            value = "".join(
                                t.text or "" for t in cell.findall(f"{S}is//{S}t")
                            )
                        elif kind == "e":
                            value = {"excel_error": value}
                        elif kind == "b":
                            value = value == "1"
                        elif kind not in {"str", "d"} and value is not None:
                            value = float(value)
                            if not math.isfinite(value):
                                value = None
                        cells[column] = value
                    rows.append({"excel_row": number, "cells": cells})
                row.clear()
        strings = {}
        if needed:
            with archive.open("xl/sharedStrings.xml") as stream:
                index = 0
                for event, item in ET.iterparse(stream, events=("end",)):
                    if item.tag == S + "si":
                        if index in needed:
                            strings[index] = "".join(
                                t.text or "" for t in item.iter(S + "t")
                            )
                        item.clear()
                        if len(strings) == len(needed):
                            break
                        index += 1
            if needed - set(strings):
                raise ValueError("Missing shared strings")
        for row in rows:
            for column, value in row["cells"].items():
                if isinstance(value, dict) and "_shared" in value:
                    row["cells"][column] = strings[value["_shared"]]
    return {
        "path": str(source),
        "sheet": sheet_name,
        "start_row": start_row,
        "requested_rows": count,
        "date_system": "1904" if date1904 else "1900",
        "headers": [h for h in headers if columns is None or h["column"] in columns],
        "rows": rows,
        "warning": "Values/formulas are cached workbook values. Timestamp serials, units, sensor validity and alignment require interpretation; this tool does not establish steady state.",
    }
