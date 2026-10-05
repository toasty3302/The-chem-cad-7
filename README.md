# CHEMCAD MCP

A Windows stdio MCP server for Claude Code, Claude Desktop, Codex, and OpenCode.
It uses CHEMCAD's native out-of-process COM automation server. The implementation
was derived from an installed `chemcad.tlb`, COM registration, bundled help,
PE metadata, and live automation calls.

Windows only. macOS, Linux, WSL, and remote CHEMCAD backends are not supported.
This repository does not include CHEMCAD or bypass its licensing.

## Setup after cloning

Install a licensed CHEMCAD installation with the `CHEMCAD.VBServer` COM automation
feature first. Clone/download this repository into a writable directory (not
`Program Files`). From the clone directory, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup downloads uv from its official installer if needed, installs Python 3.12
if needed, and installs the dependencies pinned in `uv.lock` into `.venv`.
Internet access is needed on first installation. No administrator access is
required for the bridge; CHEMCAD installation/licensing is separate.
The command changes execution policy only for that PowerShell process.

Setup checks MCP and the bundled API catalog without opening CHEMCAD. It checks
COM registration without activating the engine, then configures Claude Code,
Claude Desktop, Codex, and OpenCode for the current Windows user. Clients must
be installed separately. Close the clients before setup, then restart them.

Existing configs are backed up beside their originals as
`*.before-chemcad-*`. Only the `chemcad` server entry is changed; unrelated
settings and other servers are preserved, including TOML and JSONC comments
outside that entry. A malformed selected config aborts registration before any
client configs are changed. Running setup again is safe and does not create
new backups when the entry is already correct.

Optional switches (invoke directly from PowerShell to pass a client array):

```powershell
# Configure only selected clients.
& .\setup.ps1 -Clients claude-code,codex

# Install and generate snippets, without changing any user/client config.
& .\setup.ps1 -GenerateOnly

# Reregister an already installed environment, without downloading dependencies.
& .\setup.ps1 -SkipInstall

# Prepare configs on a machine where CHEMCAD isn't installed yet.
& .\setup.ps1 -GenerateOnly -SkipChemcadCheck
```

`-SkipChemcadCheck` does not make simulation tools work without CHEMCAD.
`-ConfigRoot <directory>` redirects all client configs to an isolated test home.
Generated, machine-specific snippets live in the ignored `work/client-configs/`.
Keep the clone in place: client commands use its absolute Python path. Rerun
setup after moving it. The static examples in `configs/` are placeholders.

The tested installation is CHEMCAD NXT 1.2.1, with engine version reported by COM
as `8210`. Other versions need validation. 64-bit Python can drive its 32-bit
out-of-process server. The package requires Python 3.11+ if installed manually.

## Run

Clients start the server automatically. To start it manually from the clone:

```powershell
& .\.venv\Scripts\python.exe -m chemcad_mcp.server
```

This command waits silently for an MCP client. Stdout contains MCP messages;
diagnostics go to stderr. CHEMCAD starts only when a tool needs a connection.
No OpenAI or Anthropic API key is required by the server.

## Connect clients

Setup handles these registrations; the following commands and paths are useful
for manual configuration or troubleshooting.

### Claude Code

```powershell
$pythonExe = (Resolve-Path .\.venv\Scripts\python.exe).Path
claude mcp add --scope user --env CHEMCAD_MCP_TIMEOUT=180 --transport stdio chemcad -- $pythonExe -m chemcad_mcp.server
```

Use `/mcp` in a new Claude Code session to check the connection. Setup writes the
user-level `.claude.json` (or the custom `CLAUDE_CONFIG_DIR` location).
The generated `work/client-configs/claude-code.json` is also suitable for a
project `.mcp.json`.

### Claude Desktop

Merge the generated `mcpServers.chemcad` entry from `work/client-configs/claude-desktop.json` into
`%APPDATA%\Claude\claude_desktop_config.json`. Restart Claude Desktop.
Preserve existing preferences and other servers.

### Codex

Merge `work/client-configs/codex.toml` into the active Codex `config.toml`:
normally `%USERPROFILE%\.codex\config.toml`, or `%CODEX_HOME%\config.toml`
when CODEX_HOME is set. Setup honors that variable.
The 200-second tool timeout accommodates the observed automation startup delay.

### OpenCode

Merge the generated `mcp.chemcad` entry from `work/client-configs/opencode.json` into
`%USERPROFILE%\.config\opencode\opencode.json` or a project `opencode.json`.
The timeout is in milliseconds. Setup honors `XDG_CONFIG_HOME` and
`OPENCODE_CONFIG`, and updates existing `opencode.json` and `opencode.jsonc`
files without discarding comments. Project-level overrides can still take
precedence over user-level config. Restart OpenCode and run `opencode mcp list`.

Configuration references:
[Codex](https://developers.openai.com/codex/mcp),
[Claude Code](https://code.claude.com/docs/en/mcp),
[OpenCode](https://opencode.ai/docs/mcp-servers/).

## Use

Example prompt:

> Use CHEMCAD to open the flash example read-only, summarize its flowsheet,
> and report stream 1's temperature, pressure, vapor fraction, and component flows.

For experiments, ask the client to open an existing simulation with
`read_only=false` and `copy_to` set to a new filename. Existing copy targets
are rejected. Edits remain in memory until `save_simulation` writes the loaded
file. Opening another simulation, closing, or disconnecting discards unsaved edits.

| Tool | Purpose |
| --- | --- |
| `describe_chemcad_api` | Browse native signatures and enumeration constants without starting CHEMCAD |
| `connect_chemcad`, `chemcad_status`, `disconnect_chemcad` | Manage and inspect this server's automation session |
| `open_simulation`, `close_simulation`, `save_simulation` | Load a file, close it, or persist edits |
| `flowsheet_summary`, `list_components` | Read topology, equipment errors, and component order |
| `read_stream`, `write_stream` | Inspect or change stream state and composition |
| `read_unitop_parameter`, `write_unitop_parameter` | Read or change a numeric equipment parameter |
| `run_simulation` | Run all or selected steady-state units, or dynamic steps |
| `flash_tp` | Calculate a TP flash using the loaded model's thermodynamics |
| `invoke_chemcad` | Use additional methods exposed by the native automation interfaces |
| `list_simulation_templates`, `inspect_simulation_archive` | Discover and inspect local licensed templates without opening CHEMCAD |
| `create_simulation_from_template` | Copy a template or construct experimental calculation topology in a new file |
| `unitop_parameter_catalog`, `configure_unitop` | Inspect parameter names/units and configure several parameters together |
| `write_stream_by_component`, `write_feed` | Set flows by component name/database ID, or feed mole fractions and total flow |
| `configure_stoichiometric_reactor` | Set named REAC stoichiometry, key reactant and conversion |
| `simulation_results` | Read SI stream results, equipment errors and stream energy/component differences |
| `run_parameter_sensitivity` | Sweep one parameter, collect converged outputs, restore and rerun baseline |
| `calculate_chp_metrics` | Separate electrical and CHP efficiency, including losses and duct-firing fuel |
| `read_xlsx_headers`, `read_xlsx_rows`, `screen_operating_points` | Inspect headers or explicit bounded data windows; screen observations against outages/transients |

Stream tools use kelvin, absolute pascals, watts, and kmol/hour. Native internal
units are degrees Rankine, psia, Btu/hour, and lbmol/hour. Component arrays follow
the one-based position order returned by `list_components`; database IDs and
component positions are different quantities. Unit-operation parameter IDs and
their units must be taken from the equipment model documentation.

`write_stream` can reflash using the stream's existing flash specification.
For a different specification use the documented modern native stream method
through `invoke_chemcad`. `flash_tp` uses scratch flash and enthalpy objects and
leaves the flowsheet's stream values unchanged. It returns liquid and vapor
compositions and calculates phase enthalpies with the model's enthalpy interface.

## Model-building workflow (experimental)

The server now exposes 30 tools. Restart the MCP client/server after updating the
clone so it discovers the new tools; no client-config change is needed.

Use `list_simulation_templates` to discover examples from the local CHEMCAD
installation. A plain `create_simulation_from_template` call with just
`template_path` and `output_path` copies an entire working model byte-for-byte.
The output must be a new `.ccsim` file; existing targets are always rejected.
Open the result writable, inspect `unitop_parameter_catalog`, configure inputs,
run it, check equipment errors and results, then save explicitly.

For experimental equipment/connectivity creation, supply unit declarations and
stream connections. For example, to append a mixer to the discovered gas-turbine
template's final stream:

```json
{
  "template_path": "C:\\path\\Gas turbine simulation.ccsim",
  "output_path": "C:\\path\\work\\new-model.ccsim",
  "acknowledge_stale_drawing": true,
  "unitops": [
    {"id": 9, "prototype_id": 2, "label": "Added mixer", "inlets": [10], "outlets": [11]}
  ],
  "connections": [
    {"id": 10, "source_unitop": 8, "target_unitop": 9},
    {"id": 11, "source_unitop": 9, "target_unitop": 0}
  ]
}
```

IDs/prototypes in this example belong to that particular template, not every
model. Inspect the actual archive first. Endpoint `0` means a boundary feed or
product. New equipment needs distinct, ordered `inlets`/`outlets` matching the
stream endpoints; order matters for heat exchangers. `prototype_path` optionally
selects equipment from another licensed archive. Across different component
lists, only COMP, EXPN, HTXR, MIXE, PUMP and VALV prototypes are allowed. Other
categories require identical original component order. With
`replace_topology=true`, declarations replace the logical equipment/streams
rather than appending them. Inherited specifications and control metadata can
still refer to original equipment: use a simple template and configure/validate
the entire resulting model.

Important limitation: the binary GUI drawing is inherited, not regenerated.
CHEMCAD's calculation topology can contain equipment/connections absent from
that drawing. The tool requires `acknowledge_stale_drawing=true` for any logical
modification and returns a warning. This is not seamless graphical model
creation. Do not use or edit the inherited drawing as an authoritative diagram.
Always run/check the calculation model and save/reopen it; treat this path as
experimental and use disposable files.

### Additional components

Changing only XML component IDs does not supply thermodynamic properties.
`component_imports` instead appends ordinary databank components using pure
properties from selected components in a local licensed donor archive:

```json
"component_imports": [
  {
    "id": 3,
    "donor_path": "C:\\path\\licensed-donor.ccsim",
    "zero_flow_stream_id": 1,
    "zero_flow_position": 5
  }
]
```

Component ID `3` is Ethane; ID `2` is Methane and ID `1` is Hydrogen. IDs and
one-based component positions are not interchangeable. Before importing,
open the template read-only and use `read_stream` to verify the specified
existing stream/component value is exactly zero. The first import supplies that
opaque zero-flow prototype for every new component; subsequent imports only
need `id` and `donor_path`. After creation, verify the new names and zero flows
with COM before specifying feeds.

Import uses a bundled 32-bit Windows PowerShell helper and the Windows Jet 4.0
provider. Only a temporary property database is written; installed templates
remain unchanged. No proprietary numerical properties or models are included
in this repo. Imports require matching database schemas and ordinary component
IDs below 5000. No component deletion/reordering, binary-interaction merging,
custom/pseudocomponent or electrolyte support is provided. Pure-property import
does not establish that a chosen thermodynamic method is appropriate.

For a model containing a Gibbs reactor, imports also extend the supported
plaintext reaction-element matrix using the licensed database's atom counts.
Only existing element columns are supported: importing a new element (such as
sulfur into a C/H/O/N/Ar template) fails clearly instead of silently treating
the added fuel as inert. Use a compatible template for new elements. Inspect
reactant conversion, atom balances and energy, not just component names or run
status. `python scripts/validate_gibbs_imports.py` verifies ethane combustion and
saved/reopened outputs on a disposable licensed example.

Set `CHEMCAD_MCP_INSTALL_DIR` and/or `CHEMCAD_MCP_EXAMPLES_DIR` in your server's
environment for a nonstandard installation/examples location. Default parameter
catalogs are read from the installed `$<category>.LAB` files. Catalog names are
lowercase underscore labels, e.g. `efficiency` and `pressure_ratio`; use numeric
ID strings if a normalized label is ambiguous. Equipment configuration uses
current flowsheet units by default, not SI. The catalog reports native units;
mode/enum meanings still require the equipment documentation.
`specification_position` is the installed LAB position; `parameter_id` is the
legacy COM index including the equipment-ID header (LAB position + 1). For
example, compressor efficiency is LAB position 4 but native parameter ID 5 in
the tested engine. Use catalog IDs for the low-level parameter/sweep tools.
Named tools check that header at runtime and reject an unsupported layout.

Raw COMP/EXPN `actual_power` parameters (`user_units=false`) use Btu/hour,
even when the catalog's **current flowsheet units** show horsepower. Convert
raw power to watts using `1055.05585262 / 3600`, or request user units and use
the catalog's displayed unit. Negative expander power means shaft generation.
Check shaft work against the adiabatic stream enthalpy difference; the live
disposable-example check is `python scripts/validate_power_units.py`.

`configure_unitop` validates all inputs before writing and attempts to restore
previous values after a native write/readback failure. Rollback errors are
reported; this is not a transactional guarantee from CHEMCAD. Sensitivity sweeps
restore the original varied parameter and rerun the baseline in a `finally`
block. They never save automatically, and rerunning can change calculated
outputs. Inspect baseline status after the sweep. Whole sweeps share one worker
timeout: reduce point count or raise both worker/client timeouts for slow models.

### Plant-data and CHP safeguards

`read_xlsx_headers` reads only row 1, locally, with a streaming ZIP/XML reader.
It does not upload files or scan measurement rows. Headers establish available
tag names, not operating-point values or trustworthy units. A calibrated plant
model still needs a numeric operating point with synchronized timestamps and
verified fuel-flow, pressure and power units.

Once the user requests measurement inspection, `read_xlsx_rows` can read an
explicit window of up to 1000 rows from one sheet, optionally restricted to
Excel column letters. It returns raw numeric timestamp serials and the workbook's
date system, not guessed dates/units. Align sheets by timestamps: exports can
start at different times, so matching row numbers is unsafe. Missing/error values
remain distinguishable from zero; formulas use cached results. No full-dataset
scan or upload is performed automatically.

`screen_operating_points` accepts already supplied observations and explicit
ISO outage intervals, plus a configurable startup/shutdown buffer (30 minutes by
default). Supply one turbine at a time; do not substitute another turbine during
outages. Nonpositive/nonfinite fuel or power and electrical efficiencies above
one are rejected. This screening is not proof of steady state: inspect stable
load and sensor validity separately. Private plant-specific outage schedules
are not baked into the public server.

`calculate_chp_metrics` keeps electrical efficiency separate from total useful
CHP efficiency, includes gearbox/generator losses and auxiliary loads, and adds
duct-firing fuel to the denominator. All fuel must use the same LHV or HHV
basis. Zero-fuel/offline points produce no efficiency. Do not use an invalid
stack-temperature report as a heat-recovery validation target.

`simulation_results` reports stream enthalpy and component-flow differences.
These are not complete energy-balance closure residuals: external heat/shaft
work must be accounted for separately. Reactions do not conserve individual
species or total molar flow. A successful run alone is not engineering validation.

## Native API access

`chemcad://api` is an MCP resource with the recovered method catalog. The same
catalog is available through `describe_chemcad_api`. Native COM return codes
vary by method: stream array operations return component counts, simulation
runs return zero on success, and individual parameter reads return one when found.

Example `invoke_chemcad` arguments for `streams.GetStreamByID`, with four components:

```json
{
  "surface": "streams",
  "method": "GetStreamByID",
  "arguments": {
    "streamID": 1,
    "tempR": 0.0,
    "presPsia": 0.0,
    "moleVapFrac": 0.0,
    "enthBtu_Hr": 0.0,
    "compFlowLbmol_Hr": {
      "type": "array_r4",
      "value": [0, 0, 0, 0, 0],
      "byref": true
    }
  }
}
```

The response includes `return_value` and modified `references`. Legacy numeric
arrays reserve index zero; allocate N+1 elements and place values at indexes
1..N. The high-level tools handle that automatically. Newer methods with explicit
output parameters return their arrays directly through VARIANT references.

Supported descriptor types: `i2`, `i4`, `r4`, `r8`, `bstr`, `variant`,
`array_i2`, `array_i4`, `array_r4`, `array_r8`, `array_bstr`.
Lifecycle methods use the dedicated tools so the tracked file and read-only
state stay consistent. Mutating native methods require a writable simulation.

## Architecture and limits

Each MCP process owns a separate COM worker process initialized as a Windows
single-threaded apartment. A lock serializes requests and a timeout discards a
stalled worker, preventing a late response from being mistaken for another call's
result. The worker launches without a console window. The native application
may display dialogs, depending on CHEMCAD configuration and licensing.
The worker restores `WINDIR` when MCP clients omit it; CHEMCAD's Access ODBC
driver needs this Windows variable to resolve its system DLL path.

`CHEMCAD_MCP_TIMEOUT` sets the worker timeout in seconds, default 180. Raise both
this value and the client's tool timeout for long simulations. A timed-out or
cancelled operation loses its worker connection; reopen the saved file to recover.
Changes from an interrupted native call may be incomplete and are not saved
automatically. Each connected client can consume its own CHEMCAD license/session.

The native COM API supports editing/running existing models, but does not expose
creation of symbols, connections or component lists. Experimental archive tools
provide logical construction/property imports with the limits described above;
they do not add undocumented COM methods or regenerate graphical symbols.
The installed library is cataloged; methods outside the live
validation workflow still require verification for their particular data formats.
Dynamic runs are implemented but need a suitable dynamic model for validation.

## Verification and inspection

```powershell
uv sync --frozen --extra dev
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\smoke_test.py
.venv\Scripts\python.exe scripts\smoke_test.py --live
.venv\Scripts\python.exe scripts\validate_model_tools.py
.venv\Scripts\python.exe -m chemcad_mcp.server --list-api
```

The live smoke test opens a vendor example read-only, verifies stream units and
topology, checks read-only rejection, runs a flash, reads native reference outputs,
edits a fresh copy, runs and saves it, reopens it, and checks that edits persisted.
It verifies the original file's SHA-256 remains unchanged. Generated copies stay
under `work/validation-*` and the report is written to `docs/live-validation.json`.

`scripts/inspect_installation.py` regenerates the bundled API catalog and
`docs/installation-metadata.json` from the installed type library and selected PE
files. `scripts/probe_com.py` performs direct native reads for diagnosis.
See `docs/reverse-engineering.md` for findings and evidence.

The model-tools validation script uses disposable copies under ignored `work/`,
tests native topology/property imports, a 50 kW heat-exchanger energy transfer,
reactor configuration and sensitivity restoration, and checks source-file hashes.
It closes its model/session afterward. Optional
`--headers "C:\\path\\workbook.xlsx"` inspects only the workbook's first row.
Private course documents, workbooks, property databases and generated models
are ignored by Git. Keep all local plant artifacts under `work/`; inspect
`git status` before publishing.

## Why did I do this

I have better things to do than CHEME classes ¯\_(ツ)_/¯
