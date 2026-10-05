import pytest

from chemcad_mcp.api import describe_api
from chemcad_mcp.worker import Automation


def test_read_only_blocks_native_mutations_before_com_activation():
    automation = Automation()
    automation.path = "test.ccsim"
    with pytest.raises(ValueError, match="read-only"):
        automation.invoke(
            "unitops", "PutUnitOpPar", {"unitOpID": 1, "parID": 2, "parVal": 1.0}
        )
    assert automation.root is None


@pytest.mark.parametrize(
    "method",
    ["LoadJob", "LoadSim", "SaveSimulation", "CloseSimulation", "SwitchWorkDir"],
)
def test_native_lifecycle_cannot_bypass_session_tracking(method):
    with pytest.raises(ValueError, match="dedicated"):
        Automation().invoke("server", method)


def test_copy_refuses_existing_target_and_preserves_contents(tmp_path):
    source, target = tmp_path / "source.ccsim", tmp_path / "target.ccsim"
    source.write_bytes(b"source")
    target.write_bytes(b"existing model")
    with pytest.raises(FileExistsError):
        Automation().open_simulation(str(source), False, str(target))
    assert target.read_bytes() == b"existing model"
    assert source.read_bytes() == b"source"


def test_api_contains_recovered_byref_and_enum_types():
    stream = describe_api("streams", "GetStreamByID")
    assert stream["parameters"][1]["vartype"] == 0x4004
    assert describe_api()["constants"]["STREAM_STATUS_NO_ERROR"] == 0


def test_unknown_surface_and_method_are_rejected_without_com_activation():
    with pytest.raises(ValueError, match="Unknown surface"):
        Automation().invoke("arbitrary", "Run")
    with pytest.raises(ValueError, match="Unknown method"):
        Automation().invoke("server", "ExecuteScript")
