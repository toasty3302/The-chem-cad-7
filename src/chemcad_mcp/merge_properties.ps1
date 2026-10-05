param([Parameter(Mandatory=$true)][string]$JobPath)
# This helper only writes the temporary database prepared by archives.py.
# Installed examples/databanks are read, never modified or redistributed.
$ErrorActionPreference = 'Stop'
# MCP clients omit these variables; Jet resolves external database providers
# through their expanded registry paths. Restore them only in this subprocess.
if (-not $env:CommonProgramFiles) { $env:CommonProgramFiles = [Environment]::GetFolderPath('CommonProgramFiles') }
if (-not $env:ProgramFiles) { $env:ProgramFiles = [Environment]::GetFolderPath('ProgramFiles') }
$job = Get-Content -LiteralPath $JobPath -Raw | ConvertFrom-Json
$destinationPath = (Resolve-Path -LiteralPath $job.destination).Path
$connection = New-Object -ComObject ADODB.Connection
$imports = @()
try {
    $connection.Provider = 'Microsoft.Jet.OLEDB.4.0'
    $connection.Properties.Item('Data Source').Value = $destinationPath
    $connection.Mode = 3
    $connection.Open()
    [void]$connection.BeginTrans()
    try {
        foreach ($item in $job.imports) {
            $external = (Resolve-Path -LiteralPath $item.donor).Path.Replace("'", "''")
            $componentId = [int]$item.id
            $row = $connection.Execute("SELECT THE_GUID FROM GUID_TRANSLATION IN '$external' WHERE OLD_CHEMCAD_ID=$componentId")
            if ($row.EOF) { throw "Component $componentId absent from donor" }
            $guid = $row.Fields.Item('THE_GUID').Value
            $row.Close()
            $row = $connection.Execute("SELECT COMPONENT_NAME, MOLECULAR_WT, ELECTROLYTE_STATE FROM MAINDATA IN '$external' WHERE THE_GUID = {guid $guid}")
            if ($row.EOF -or $row.Fields.Item('MOLECULAR_WT').Value -le 0 -or $row.Fields.Item('ELECTROLYTE_STATE').Value -ne 0) {
                throw "Only ordinary non-electrolyte components are supported: $componentId"
            }
            $componentName = [string]$row.Fields.Item('COMPONENT_NAME').Value
            $row.Close()
            $existing = $connection.Execute("SELECT THE_GUID FROM GUID_TRANSLATION WHERE OLD_CHEMCAD_ID=$componentId")
            if (-not $existing.EOF) { throw "Component $componentId already exists in destination property database" }
            $existing.Close()
            foreach ($table in @('MAINDATA','GUID_TRANSLATION','LIBRARY','ATOMS','SYNONYM','EBIPS','OLD_COMPONENT_GROUP_DATA')) {
                $fields = $connection.Execute("SELECT TOP 1 * FROM [$table]")
                $sourceFields = $connection.Execute("SELECT TOP 1 * FROM [$table] IN '$external'")
                $sourceNames = @($sourceFields.Fields | ForEach-Object { $_.Name })
                $columns = ($fields.Fields | Where-Object { $sourceNames -contains $_.Name } | ForEach-Object { '[' + $_.Name + ']' }) -join ','
                $fields.Close()
                $sourceFields.Close()
                $guidColumn = if ($table -eq 'EBIPS') { 'GUID_COMPONENT' } else { 'THE_GUID' }
                [void]$connection.Execute("INSERT INTO [$table] ($columns) SELECT $columns FROM [$table] IN '$external' WHERE [$guidColumn] = {guid $guid}")
            }
            $atomRows = $connection.Execute("SELECT ATOMIC_NUMBER, ATOM_COUNT FROM ATOMS WHERE THE_GUID = {guid $guid}")
            $atoms = @()
            while (-not $atomRows.EOF) {
                $atoms += @{ atomic_number = [int]$atomRows.Fields.Item('ATOMIC_NUMBER').Value; count = [double]$atomRows.Fields.Item('ATOM_COUNT').Value }
                $atomRows.MoveNext()
            }
            $atomRows.Close()
            $imports += @{ id = $componentId; name = $componentName; atoms = @($atoms) }
        }
        $connection.CommitTrans()
    } catch {
        $connection.RollbackTrans()
        throw
    }
    ConvertTo-Json -InputObject @{ components = @($imports) } -Depth 6 -Compress
} finally {
    if ($connection.State -ne 0) { $connection.Close() }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($connection)
}
