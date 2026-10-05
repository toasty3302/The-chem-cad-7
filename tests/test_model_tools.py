import zipfile
from types import SimpleNamespace

import pytest

from chemcad_mcp.archives import ModelArchive, create_model, list_templates
from chemcad_mcp.datasets import read_xlsx_headers, read_xlsx_rows
from chemcad_mcp.engineering import (
    chp_metrics,
    component_vector,
    screen_operating_points,
)
from chemcad_mcp.installation import parameter_definitions
from chemcad_mcp.worker import Automation


def test_gibbs_element_matrix_extends_imports_and_rejects_unknown_elements():
    from chemcad_mcp.archives import _extend_gibbs_element_matrix

    data = {
        ".400": ("model.400", b"4 C H\n6 1\n1 2\n2 1 4\n"),
        ".grd": (
            "$ATOM.GRD",
            b'Component Element Matrix\nCOL 2\nC\nH\nROW 1\n"Methane"\nREAD-ONLY_CELLS 0\nREAD-ONLY_ROWS 1\n0\n',
        ),
    }
    model = SimpleNamespace(component_ids=[2], data=lambda suffix: data[suffix])
    imported = [
        {
            "id": 3,
            "name": "Ethane",
            "atoms": [
                {"atomic_number": 6, "count": 2},
                {"atomic_number": 1, "count": 6},
            ],
        }
    ]
    output = _extend_gibbs_element_matrix(model, imported, grid_data=data[".grd"])
    assert output["model.400"].decode().splitlines()[-1].split() == ["3", "2", "6"]
    grid = output["$ATOM.GRD"].decode()
    assert 'ROW 2\n"Methane"\n"Ethane"' in grid
    assert grid.endswith("READ-ONLY_ROWS 2\n0\n1\n")
    imported[0]["atoms"].append({"atomic_number": 8, "count": 1})
    with pytest.raises(ValueError, match="element"):
        _extend_gibbs_element_matrix(model, imported, grid_data=data[".grd"])


@pytest.fixture
def template(tmp_path):
    # Synthetic logical schema only; no vendor fields/records in repository.
    path = tmp_path / "template.ccsim"
    xml = b"""<CHEMCAD version="6"><TLK><GeneralInfo NumberOfComponents="1"/><ComponentIDs><Component ID="62"/></ComponentIDs></TLK>
    <Equipment><UnitOp ide="1" ename="MIXE"><ioe><Item key="0" data="1"/><Item key="1" data="1"/><Item key="2" data="-2"/></ioe><eqs schema="2"/></UnitOp></Equipment>
    <Streams><Stream ID="1"><issdi issdi0="1" issdi1="0" issdi2="1"/><Components><item key="0" data="opaque-zero"/></Components></Stream>
    <Stream ID="2"><issdi issdi0="2" issdi1="1" issdi2="0"/><Components><item key="0" data="opaque-zero"/></Components></Stream></Streams></CHEMCAD>"""
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr("template.xml", xml)
        archive.writestr("template.flwshtcc7", b"synthetic drawing")
        archive.writestr("template.ppdb", b"synthetic property database")
    return path


def test_exclusive_template_copy(template):
    destination = template.with_name("copy.ccsim")
    result = create_model(str(template), str(destination))
    assert result["copied"]
    assert template.read_bytes() == destination.read_bytes()
    with pytest.raises(FileExistsError):
        create_model(str(template), str(destination))


def test_model_requires_stale_drawing_acknowledgement(template):
    with pytest.raises(ValueError, match="acknowledge_stale_drawing"):
        create_model(
            str(template), str(template.with_name("new.ccsim")), connections=[{}]
        )


def test_construct_unitop_and_connections_preserves_template_and_binary(template):
    original = template.read_bytes()
    destination = template.with_name("new.ccsim")
    result = create_model(
        str(template),
        str(destination),
        unitops=[
            {
                "id": 2,
                "prototype_id": 1,
                "inlets": [2],
                "outlets": [3],
                "label": "New mixer",
            }
        ],
        connections=[
            {"id": 2, "source_unitop": 1, "target_unitop": 2},
            {"id": 3, "source_unitop": 2, "target_unitop": 0},
        ],
        acknowledge_stale_drawing=True,
    )
    assert result["unitop_count"] == 2 and result["stream_count"] == 3
    model = ModelArchive(destination)
    assert model.describe()["unitops"][1]["label"] == "New mixer"
    assert [
        int(i.get("data"))
        for i in model.root.findall("Equipment/UnitOp")[1].find("ioe")
    ] == [2, 2, -3]
    assert model.data(".flwshtcc7")[1] == b"synthetic drawing"
    assert template.read_bytes() == original


@pytest.mark.parametrize("unit_id", [0, -1, 32768, True, "2"])
def test_invalid_unit_ids_rejected_before_output(template, unit_id):
    destination = template.with_name("bad.ccsim")
    with pytest.raises(ValueError):
        create_model(
            str(template),
            str(destination),
            unitops=[{"id": unit_id}],
            acknowledge_stale_drawing=True,
        )
    assert not destination.exists()


def test_invalid_ports_or_endpoints_rejected(template):
    with pytest.raises(ValueError, match="endpoints"):
        create_model(
            str(template),
            str(template.with_name("bad.ccsim")),
            connections=[{"id": 2, "source_unitop": 1, "target_unitop": 7}],
            acknowledge_stale_drawing=True,
        )
    with pytest.raises(ValueError, match="disagree"):
        create_model(
            str(template),
            str(template.with_name("bad.ccsim")),
            unitops=[{"id": 2, "prototype_id": 1, "inlets": [2], "outlets": [3]}],
            acknowledge_stale_drawing=True,
        )


def test_replace_topology_and_template_search(template):
    path = template.with_name("replacement.ccsim")
    create_model(
        str(template),
        str(path),
        unitops=[{"id": 7, "prototype_id": 1, "inlets": [8], "outlets": [9]}],
        connections=[
            {"id": 8, "source_unitop": 0, "target_unitop": 7},
            {"id": 9, "source_unitop": 7, "target_unitop": 0},
        ],
        replace_topology=True,
        acknowledge_stale_drawing=True,
    )
    assert [u["id"] for u in ModelArchive(path).describe()["unitops"]] == [7]
    assert (
        len(
            list_templates(str(template.parent), required_component_ids=[62])[
                "templates"
            ]
        )
        == 2
    )
    assert not list_templates(str(template.parent), required_component_ids=[3])[
        "templates"
    ]


def test_parameter_definitions_are_runtime_not_shipped(tmp_path, monkeypatch):
    (tmp_path / "$COMP.LAB").write_text(
        "Pos. Unit Type Fmat Req. Prn0 Label\n  4 0 0 0 0 0 Efficiency\n 11 0 0 0 1 0 Pressure ratio\n"
    )
    monkeypatch.setenv("CHEMCAD_MCP_INSTALL_DIR", str(tmp_path))
    params = parameter_definitions("COMP")
    assert params[1]["name"] == "pressure_ratio"
    assert params[0]["parameter_id"] == 5
    assert params[0]["specification_position"] == 4
    with pytest.raises(ValueError):
        parameter_definitions("../arbitrary")


COMPONENTS = [{"id": 2, "name": "Methane"}, {"id": 46, "name": "Nitrogen"}]


def test_named_components_and_ids_are_not_positions():
    assert component_vector(COMPONENTS, {"methane": 3, "46": 4}) == [3, 4]
    with pytest.raises(ValueError, match="Unknown"):
        component_vector(COMPONENTS, {"1": 3})
    with pytest.raises(ValueError, match="more than once"):
        component_vector(COMPONENTS, {"2": 3, "Methane": 4})
    with pytest.raises(ValueError, match="finite"):
        component_vector(COMPONENTS, {"2": float("nan")})


def test_chp_separates_electrical_and_total_efficiency_and_duct_firing():
    result = chp_metrics(1000, 700, 200, 200, 0.98, 0.99, 10, 100)
    assert result["electrical_efficiency"] == pytest.approx(
        (500 * 0.98 * 0.99 - 10) / 1100
    )
    assert result["total_chp_efficiency"] == pytest.approx(
        (500 * 0.98 * 0.99 - 10 + 200) / 1100
    )
    assert chp_metrics(0, 0, 0)["electrical_efficiency"] is None
    assert chp_metrics(10, 15, 0)["warnings"]
    with pytest.raises(ValueError):
        chp_metrics(10, 10, 0, generator_efficiency=1.5)


def test_outage_transient_and_zero_fuel_screen():
    points = [
        {
            "timestamp": f"2025-01-01T{time}",
            "electrical_power_kw": power,
            "fuel_heat_input_kw": fuel,
        }
        for time, power, fuel in [
            ("10:00:00", 10, 30),
            ("11:00:00", 10, 30),
            ("12:05:00", 10, 30),
            ("13:00:00", 0, 0),
        ]
    ]
    result = screen_operating_points(
        points, [{"start": "2025-01-01T10:30:00", "end": "2025-01-01T12:00:00"}], 15
    )
    assert result["eligible_count"] == 1
    assert result["points"][1]["reasons"] == ["reported_outage"]
    assert result["points"][2]["reasons"] == ["startup_shutdown_buffer"]
    assert result["points"][3]["electrical_efficiency"] is None
    with pytest.raises(ValueError, match="timezone"):
        screen_operating_points(
            points, [{"start": "2025-01-01T10:30:00Z", "end": "2025-01-01T12:00:00Z"}]
        )


def test_read_only_blocks_new_mutating_worker_operations():
    automation = Automation()
    automation.path = "test.ccsim"
    for method, args in [
        ("configure_unitop", (1, {"4": 0.8})),
        ("write_feed", (1, 300, 1e5, 100, {"Water": 1})),
        ("sensitivity", (1, 4, [0.8], [1])),
    ]:
        with pytest.raises(ValueError, match="read-only"):
            getattr(automation, method)(*args)
    assert automation.root is None


def test_configuration_validates_before_writing_and_rolls_back(monkeypatch):
    automation = Automation()
    automation.path, automation.read_only = "test.ccsim", False
    monkeypatch.setattr(
        automation,
        "unitop_catalog",
        lambda *a, **k: {
            "parameters": [
                {"parameter_id": 4, "name": "efficiency", "integer": False},
                {"parameter_id": 1, "name": "mode", "integer": True},
            ]
        },
    )
    state, writes = {4: 0.8, 1: 0}, []

    def parameter(uid, pid, user_units=True, value=None):
        if value is not None:
            writes.append((pid, value))
            if pid == 1 and value == 1:
                raise RuntimeError("native failure")
            state[pid] = value
        return {"value": state[pid]}

    monkeypatch.setattr(automation, "unitop_parameter", parameter)
    with pytest.raises(ValueError, match="Unknown"):
        automation.configure_unitop(1, {"efficiency": 0.9, "unknown": 3})
    assert not writes
    with pytest.raises(RuntimeError, match=r"rollback errors: \[\]"):
        automation.configure_unitop(1, {"efficiency": 0.9, "mode": 1})
    assert state == {4: 0.8, 1: 0}


def test_sweep_restores_and_reruns_after_failed_run(monkeypatch):
    automation = Automation()
    automation.path, automation.read_only = "test.ccsim", False
    state, runs = [0.8], []
    monkeypatch.setattr(automation, "valid_id", lambda *a, **k: None)

    def parameter(uid, pid, user_units=True, value=None):
        if value is not None:
            state[0] = value
        return {"value": state[0]}

    def run():
        runs.append(state[0])
        if state[0] == 0.9:
            raise RuntimeError("run failed")
        return {"success": True}

    monkeypatch.setattr(automation, "unitop_parameter", parameter)
    monkeypatch.setattr(automation, "run_simulation", run)
    with pytest.raises(RuntimeError, match="run failed"):
        automation.sensitivity(1, 4, [0.9], [1])
    assert state == [0.8] and runs == [0.9, 0.8]


def test_screen_rejects_mixed_turbines_and_boolean_measurements():
    point = {
        "timestamp": "2025-01-01T00:00:00",
        "electrical_power_kw": 10,
        "fuel_heat_input_kw": 30,
    }
    with pytest.raises(ValueError, match="one turbine"):
        screen_operating_points(
            [{**point, "turbine_id": 1}, {**point, "turbine_id": 2}]
        )
    assert (
        screen_operating_points([{**point, "fuel_heat_input_kw": True}])[
            "eligible_count"
        ]
        == 0
    )


def test_reactor_stoichiometry_uses_offset_and_prevalidates_key(monkeypatch):
    automation = Automation()
    automation.path, automation.read_only = "test.ccsim", False
    components = [
        {"id": 2, "name": "Methane"},
        {"id": 47, "name": "Oxygen"},
        {"id": 49, "name": "Carbon Dioxide"},
        {"id": 62, "name": "Water"},
    ]
    monkeypatch.setattr(automation, "components", lambda: components)
    monkeypatch.setattr(
        automation, "unitop_catalog", lambda *a, **k: {"category": "REAC"}
    )
    calls = []

    def configure(uid, parameters, user_units=True):
        calls.append(parameters)
        return {}

    monkeypatch.setattr(automation, "configure_unitop", configure)
    automation.configure_reactor(
        5, {"Methane": -1, "47": -2, "49": 1, "Water": 2}, "Methane", 1.0, 0
    )
    assert calls[0]["50"] == -1 and calls[0]["53"] == 2
    assert calls[0]["key_component"] == 1
    with pytest.raises(ValueError, match="reactant"):
        automation.configure_reactor(5, {"Methane": 1}, "Methane", 1.0, 0)
    automation.read_only = True
    with pytest.raises(ValueError, match="read-only"):
        automation.configure_reactor(5, {}, "Methane", 1, 0)


def test_xlsx_header_reader_stops_before_measurements(tmp_path):
    path = tmp_path / "measurements.xlsx"
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "x") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Gas" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}"><si><t>TimeStamp</t></si><si><t>.[TEST.FUEL]</t></si></sst>',
        )
        # Invalid measurement contents beyond parser's initial read buffer prove
        # it does not iterate through or validate the measurement dataset.
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="D1" t="inlineStr"><is><t>Power</t></is></c></row>'
            + " " * 65536
            + "<broken-measurement",
        )
    result = read_xlsx_headers(str(path), ["Gas"])
    assert result["row_read"] == 1
    assert [c["value"] for c in result["sheets"][0]["headers"]] == [
        "TimeStamp",
        ".[TEST.FUEL]",
        "Power",
    ]
    with pytest.raises(ValueError, match="Unknown sheets"):
        read_xlsx_headers(str(path), ["Engine"])


def test_no_component_import_from_missing_zero_prototype(template, monkeypatch):
    monkeypatch.setattr(
        "chemcad_mcp.archives._merge_properties",
        lambda *a: pytest.fail("must validate first"),
    )
    with pytest.raises(ValueError, match="zero_flow"):
        create_model(
            str(template),
            str(template.with_name("bad.ccsim")),
            component_imports=[{"id": 3, "donor_path": str(template)}],
            acknowledge_stale_drawing=True,
        )


def test_imported_components_use_the_verified_zero_prototype(template, monkeypatch):
    monkeypatch.setattr(
        "chemcad_mcp.archives._merge_properties",
        lambda *a: (
            "template.ppdb",
            b"new synthetic database",
            [{"id": 3, "name": "Ethane"}],
        ),
    )
    destination = template.with_name("new.ccsim")
    create_model(
        str(template),
        str(destination),
        component_imports=[
            {
                "id": 3,
                "donor_path": "unused",
                "zero_flow_stream_id": 1,
                "zero_flow_position": 1,
            }
        ],
        acknowledge_stale_drawing=True,
    )
    model = ModelArchive(destination)
    assert model.component_ids == [62, 3]
    assert all(
        s.find("Components/item[@key='1']").get("data") == "opaque-zero"
        for s in model.root.findall("Streams/Stream")
    )
    assert model.data(".ppdb")[1] == b"new synthetic database"


def test_bounded_measurement_reader_preserves_dates_and_missing_values(tmp_path):
    path = tmp_path / "window.xlsx"
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "x") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="1"/><sheets><sheet name="Gas" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}"><si><t>TimeStamp</t></si><si><t>Fuel</t></si><si><t>Null</t></si></sst>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2"><v>1000.5</v></c><c r="B2"><v>42</v></c></row><row r="3"><c r="A3"><v>1001.5</v></c><c r="B3" t="s"><v>2</v></c></row><row r="4"><c r="B4"><v>9999</v></c></row></sheetData></worksheet>',
        )
    result = read_xlsx_rows(str(path), "Gas", 2, 2, ["A", "B"])
    assert result["date_system"] == "1904"
    assert [r["excel_row"] for r in result["rows"]] == [2, 3]
    assert result["rows"][0]["cells"] == {"A": 1000.5, "B": 42.0}
    assert result["rows"][1]["cells"]["B"] == "Null"
    assert read_xlsx_rows(str(path), "Gas", 3, 1, ["B"])["rows"][0]["cells"] == {
        "B": "Null"
    }
    with pytest.raises(ValueError, match="count"):
        read_xlsx_rows(str(path), "Gas", count=1001)
    with pytest.raises(ValueError, match="columns"):
        read_xlsx_rows(str(path), "Gas", columns=["A1"])
