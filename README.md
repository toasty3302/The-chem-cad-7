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

This interface supports editing and running existing models. The recovered COM
API does not expose creation of flowsheet symbols, stream connections, or a new
component list. The installed library is cataloged; methods outside the live
validation workflow still require verification for their particular data formats.
Dynamic runs are implemented but need a suitable dynamic model for validation.

## Verification and inspection

```powershell
uv sync --frozen --extra dev
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\smoke_test.py
.venv\Scripts\python.exe scripts\smoke_test.py --live
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

## Publishing

Source, config templates, `.python-version`, `uv.lock`, and the bundled
`src/chemcad_mcp/api.json` belong in Git. `.gitignore` excludes local virtual
environments, generated client configs, credentials, validation output,
simulation copies, vendor binaries/help/databases, and debugger artifacts.
Ignore rules do not remove files already tracked by Git; check `git status`
and staged changes before publishing.
