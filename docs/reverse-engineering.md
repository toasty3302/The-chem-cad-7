# CHEMCAD NXT automation findings

Inspected installation: `C:\Program Files (x86)\Chemstations\CHEMCAD NXT`.
The GUI previously identified itself as CHEMCAD NXT 1.2.1.

## Evidence

- `chemcad.tlb`: 55,116 bytes; library name CHEMCAD. Extracted interface names,
  parameter names, DISPIDs, invocation kinds, native VARIANT types, reference
  flags, and enumeration constants into `src/chemcad_mcp/api.json`.
- Windows 32-bit COM registry: `CHEMCAD.VBServer` maps to CLSID
  `{2B03C5E1-25B6-11D4-BBD3-0050DACD255C}` and `CCNXT.exe` as a local server.
- `CHEMCAD_NXT.SimulationServer` has a separate CLSID
  `{c1b8fd7d-4c90-4f62-8d1b-354d4292626f}` and OPC registration. The bridge uses
  the VB automation interface described in the installed COM reference.
- PE inspection: `CCNXT.exe`, `CcxDll.dll`, `FlSht.dll`, `SimData.dll`, and
  `CCXSim.dll` are x86 (`IMAGE_FILE_MACHINE_I386`, 0x14c). Export names are in
  `docs/installation-metadata.json`.
- Bundled `chemcad.chm`: COM reference, VB server, stream, flowsheet, unit-operation,
  flash, engineering-unit, and other interface documentation. Extracted locally
  into the ignored `work/help` directory for inspection.
- The installed UAM C++ headers describe plug-in callbacks and internal units.
  They operate inside CHEMCAD, so the external bridge uses COM.

## Native behavior discovered by live calls

64-bit Python successfully activates the 32-bit COM local server by literal
CLSID. ProgID registry lookups depend on the registry view; the literal CLSID
avoids that dependency.

The live VBServer and child interfaces return `DISP_E_BADINDEX` from
`IDispatch.GetTypeInfo(0)`. Automatic wrappers which require live type information
cannot be used. Method signatures are loaded from the installed type library;
the worker resolves method names with `GetIDsOfNames` on the live object.

`GetAppVersion` returned `8210`. `GetSimulationMode` returned zero for steady state.
The work directory was the user's configured `My Simulations` directory.
The `pid` method exposes the actual automation server process ID.

`LoadSim(path, 1)` successfully opened the bundled
`_Process Simulation Essentials\2 Phase Equilibria\1 - Flash calculations.ccsim`
read-only. `GetFlowsheet` and `GetStreamInfo` returned null before a model was
loaded, then returned usable dispatch objects afterward.

The example has 18 streams and four components, ordered Benzene, Cyclohexane,
Toluene, Ethylbenzene. `GetAllStreamIDs` filled indexes 1..18 of a zero-based,
19-element VT_I2 SAFEARRAY. Index zero stayed reserved. `GetStreamByID(1)`
returned four component values in indexes 1..4 of a five-element VT_R4 SAFEARRAY.
Explicit VT_BYREF scalar and array variants are required to observe output changes.

Stream 1 native values observed during the initial direct probe:

- Temperature: 671.6699829101562 degR (about 373.15 K).
- Absolute pressure: 14.503767967224121 psia (about 100,000 Pa).
- Vapor mole fraction: 0.12474074959754944.
- Enthalpy rate: 3,334,439.5 Btu/hour.
- Component flows: approximately 110.23113, 0, 0, 110.23113 lbmol/hour
  (about 50, 0, 0, 50 kmol/hour).

## Integration choices

The native TP flash returned valid phase splits but zero enthalpy when the
defined feed enthalpy was zero, including in the phase retrieval methods.
The bridge explicitly calculates each phase's enthalpy with `IEnthalpy` and sums
the results. Validation compares the result with the precomputed stream enthalpy
at the same temperature, pressure, and composition, and checks component balances.

MCP's standard Windows environment allowlist contains `SYSTEMROOT` but omits
`WINDIR`. Under that environment CHEMCAD showed a blocking critical database
dialog: Access ODBC error 126, unable to load `%WINDIR%\\system32\\odbcjt32.dll`.
Direct shell probes worked because their environment contained `WINDIR`. The
worker restores `WINDIR` from `SYSTEMROOT`, falling back to the Windows directory
API, before activating CHEMCAD. This does not change system-wide settings.

The server uses name-based IDispatch invocation with explicit typed variants.
It owns COM objects on one STA worker process and serializes requests. The MCP
transport starts without activating CHEMCAD; file loading and calculations happen
only through tools. Read-only mode is tracked and enforced by both CHEMCAD's
`LoadSim` flag and the bridge's mutating operations.

The executable and installed DLLs were inspected as data. Binary patching and
debugger attachment were unnecessary for the discovered automation interface.
The existing IDA sessions had unrelated databases open and were preserved.

Full native numerical algorithms have not been reconstructed. The MCP server
delegates thermodynamic and simulation calculations to the installed engine.
