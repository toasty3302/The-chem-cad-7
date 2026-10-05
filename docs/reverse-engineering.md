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

## Experimental logical-model construction

NXT `.ccsim` models are ZIP containers. The primary CHEMCAD XML describes the
logical component list, equipment and stream endpoints; `.flwshtcc7` contains
the separate binary graphical drawing. Equipment `ioe` entries contain its own
ID followed by positive inlet and negative outlet stream IDs. Stream `issdi`
entries identify stream, source equipment and destination equipment (zero is
a boundary). Equipment and stream numeric schema-2 fields are opaque; the bridge
does not interpret/decrypt them. It clones valid prototypes and configures their
numerical inputs through native COM.

Live tests accepted added logical equipment and connections, including a mixer
and a heat exchanger from another licensed example. Simulation runs and
save/reopen preserved the added topology. The heat exchanger's hot/cold duties
matched an explicitly specified 50 kW transfer. However, the inherited binary
drawing was not updated. Removing it produced a loadable file without a usable
flowsheet interface. The public tool therefore retains it, requires explicit
acknowledgement, and does not claim synchronized graphical construction.

XML-only component addition returned an ID string instead of the correct name.
The associated `.ppdb` is a Jet database containing pure-property records and
GUID translations. A 32-bit PowerShell/ADO helper imports ordinary components
from local licensed donor archives into a temporary copy of that database.
Ethane, Propane, n-Butane, n-Pentane, n-Hexane and Hydrogen Sulfide were recognized
by native COM; a new Ethane component also passed a TP flash/enthalpy calculation.
Imported zero-flow fields, selected names and topology survived save/reopen.
No vendor databases or numerical records are distributed. Binary interactions,
custom components, electrolytes and component reordering remain unsupported.

Jet external-database queries failed with "Class not registered" under MCP's
reduced environment even though opening the destination database worked. Restoring
`CommonProgramFiles`/`ProgramFiles` from Windows known-folder values in the 32-bit
helper fixed that path; `WINDIR` is also restored before invoking it.

Installed `$<category>.LAB` files provide specification labels and engineering
unit IDs. Their positions are not the legacy `Get/PutUnitOpPar` indexes: the
native specification array includes an equipment-ID header. Compressor efficiency
is LAB position 4 / native parameter ID 5; heat duty is HTXR position 8 / native
ID 9. Named tools apply that offset and verify the header before accepting the
layout. `IEngUnitConversion` supplies current unit labels. A live sensitivity
sweep varied true compressor efficiency, restored it and reran the baseline.
The REAC helper also configured and ran an existing stoichiometric example using
component database IDs mapped to the correct one-based component positions.

This remains interoperability with the licensed simulation engine, not a
reconstruction of its thermodynamic algorithms or a replacement for engineering
validation. Inherited control/solver metadata may still refer to original units.
Use simple templates, disposable outputs and explicit run/error/balance checks.

## Reaction-element and shaft-power validation

An imported component can have a valid name and flash properties yet remain
outside an inherited Gibbs reactor's reaction-element table. A minimal live
combustion test initially left 1 kmol/h of newly imported ethane unchanged.
The supported plaintext `.400` atom matrix and `$ATOM.GRD` rows are now extended
from the licensed property database's `ATOMS` records. Existing element-column
definitions/reference factors are retained; a newly introduced element is
rejected instead of guessed. The ethane combustion check now passes, including
save/reopen. Low-temperature Gibbs numerical behavior still needs independent
reactant/atom checks; model creation and a zero error code are not sufficient.

Raw COMP/EXPN actual shaft power is Btu/hour, even when current user units are
horsepower. A one-compressor live regression check compares native work with
the SI stream-enthalpy rise. The Btu/hour conversion agrees to floating-point
precision; interpreting the same raw value as horsepower is wrong by roughly
2544 times. No engine algorithms or opaque numerical fields were reconstructed.
