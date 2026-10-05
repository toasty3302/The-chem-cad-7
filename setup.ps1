#Requires -Version 5.1
<#
.SYNOPSIS
Install the Windows CHEMCAD MCP bridge and configure local MCP clients.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.EXAMPLE
.\setup.ps1 -Clients codex,claude-code -GenerateOnly
#>
[CmdletBinding()]
param(
    [ValidateSet('claude-code', 'claude-desktop', 'codex', 'opencode')]
    [string[]] $Clients = @('claude-code', 'claude-desktop', 'codex', 'opencode'),
    [switch] $GenerateOnly,
    [switch] $SkipInstall,
    [switch] $SkipChemcadCheck,
    [string] $ConfigRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') {
    throw 'CHEMCAD MCP supports native Windows only. WSL, macOS, and Linux are not supported.'
}
if ($Clients.Count -eq 0) { throw 'Select at least one client.' }

$projectRoot = $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'

function Invoke-Checked {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Executable"
    }
}

function Get-UvExecutable {
    $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
    if ($uvCommand) { return $uvCommand.Source }

    $localUv = Join-Path $projectRoot 'work\tools\uv\uv.exe'
    if (Test-Path -LiteralPath $localUv -PathType Leaf) { return $localUv }

    # Install into this clone, without changing the user's PATH or requiring admin.
    $bootstrapDirectory = Join-Path $projectRoot 'work\tools'
    New-Item -ItemType Directory -Force -Path $bootstrapDirectory | Out-Null
    $installer = Join-Path $bootstrapDirectory 'uv-install.ps1'
    Write-Host 'Downloading uv from https://astral.sh/uv/install.ps1 ...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer

    $previousInstallDir = [Environment]::GetEnvironmentVariable('UV_INSTALL_DIR', 'Process')
    $previousNoModifyPath = [Environment]::GetEnvironmentVariable('UV_NO_MODIFY_PATH', 'Process')
    try {
        $env:UV_INSTALL_DIR = Split-Path -Parent $localUv
        $env:UV_NO_MODIFY_PATH = '1'
        $powerShellExe = Join-Path $env:SYSTEMROOT 'System32\WindowsPowerShell\v1.0\powershell.exe'
        Invoke-Checked $powerShellExe @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer) | Out-Host
    }
    finally {
        [Environment]::SetEnvironmentVariable('UV_INSTALL_DIR', $previousInstallDir, 'Process')
        [Environment]::SetEnvironmentVariable('UV_NO_MODIFY_PATH', $previousNoModifyPath, 'Process')
    }
    if (-not (Test-Path -LiteralPath $localUv -PathType Leaf)) {
        throw 'uv installation did not produce uv.exe. Install uv manually and rerun setup.'
    }
    return $localUv
}

Push-Location -LiteralPath $projectRoot
try {
    if (-not $SkipInstall) {
        $uvExe = Get-UvExecutable
        Write-Host 'Installing the locked dependencies and Python 3.12 if needed ...'
        Invoke-Checked $uvExe @('sync', '--frozen', '--python', '3.12', '--no-dev')
    }
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw 'No .venv Python found. Rerun setup without -SkipInstall.'
    }

    $configureArguments = @('-m', 'chemcad_mcp.configure', '--output-dir', (Join-Path $projectRoot 'work\client-configs'), '--clients') + $Clients
    if ($GenerateOnly) { $configureArguments += '--generate-only' }
    if ($SkipChemcadCheck) { $configureArguments += '--skip-chemcad-check' }
    if ($ConfigRoot) { $configureArguments += @('--config-root', $ConfigRoot) }
    # The smoke test checks stdio and the API catalog, never activates CHEMCAD.
    Write-Host 'Checking MCP without opening CHEMCAD ...'
    Invoke-Checked $pythonExe @('scripts\smoke_test.py')
    Invoke-Checked $pythonExe $configureArguments
    Write-Host ''
    if ($GenerateOnly) {
        Write-Host 'Setup complete. Snippets generated only; no client configs were changed.'
    }
    else {
        Write-Host 'Setup complete. Restart your selected clients to load the chemcad server.'
    }
    Write-Host 'Keep this clone in place; rerun setup if you move it.'
}
finally {
    Pop-Location
}
