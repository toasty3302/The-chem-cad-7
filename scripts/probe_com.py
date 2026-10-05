"""Activate the installed VB automation server and make only metadata reads."""

import sys

import pythoncom
from win32com.client import VARIANT

pythoncom.CoInitialize()
try:
    clsid = pythoncom.MakeIID("{2B03C5E1-25B6-11D4-BBD3-0050DACD255C}")
    obj = pythoncom.CoCreateInstance(
        clsid, None, pythoncom.CLSCTX_LOCAL_SERVER, pythoncom.IID_IDispatch
    )

    def call(target, name, *args):
        return target.Invoke(
            target.GetIDsOfNames(name), 0, pythoncom.DISPATCH_METHOD, True, *args
        )

    try:
        print("interface:", obj.GetTypeInfo(0).GetDocumentation(-1), flush=True)
    except Exception as error:
        print("typeinfo unavailable:", repr(error), flush=True)
    for name in ("GetAppVersion", "GetWorkDir", "GetSimulationMode", "pid"):
        try:
            print(name, repr(call(obj, name)), flush=True)
        except Exception as error:
            print(name, repr(error), flush=True)
    if len(sys.argv) > 1:
        print("LoadSim:", call(obj, "LoadSim", sys.argv[1], 1), flush=True)
    for name in ("GetFlowsheet", "GetStreamInfo", "GetUnitOpInfo"):
        try:
            child = call(obj, name)
            print(name, type(child), repr(child), flush=True)
            if hasattr(child, "GetTypeInfo"):
                try:
                    print(
                        "child interface",
                        child.GetTypeInfo(0).GetDocumentation(-1),
                        flush=True,
                    )
                except Exception as error:
                    print("child typeinfo unavailable", repr(error), flush=True)
                if name == "GetFlowsheet":
                    count = call(child, "GetNoOfStreams")
                    ids = VARIANT(
                        pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_I2,
                        [0] * (count + 1),
                    )
                    print(
                        "streams",
                        count,
                        "ids returned",
                        call(child, "GetAllStreamIDs", ids),
                        "ids",
                        ids.value,
                        flush=True,
                    )
                if name == "GetStreamInfo":
                    count = call(child, "GetNoOfComponents")
                    print("components", count, flush=True)
                    for i in range(1, count + 1):
                        print(
                            i,
                            call(child, "GetComponentNameByPosBaseOne", i),
                            flush=True,
                        )
                    scalars = [
                        VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R4, 0.0)
                        for _ in range(4)
                    ]
                    rates = VARIANT(
                        pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_R4,
                        [0.0] * (count + 1),
                    )
                    print(
                        "stream1",
                        call(child, "GetStreamByID", 1, *scalars, rates),
                        "scalars",
                        [v.value for v in scalars],
                        "rates",
                        rates.value,
                        flush=True,
                    )
        except Exception as error:
            print(name, repr(error), flush=True)
finally:
    pythoncom.CoUninitialize()
