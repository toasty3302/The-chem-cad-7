param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$Donor,
    [int]$ComponentId = 3
)
$ErrorActionPreference = 'Stop'
$destinationPath = (Resolve-Path -LiteralPath $Destination).Path
if (-not $destinationPath.StartsWith((Join-Path (Split-Path $PSScriptRoot -Parent) 'work') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Probe destination must be under this project work directory'
}
$donorPath = (Resolve-Path -LiteralPath $Donor).Path
$connection = New-Object -ComObject ADODB.Connection
try {
    $connection.Provider = 'Microsoft.Jet.OLEDB.4.0'
    $connection.Properties.Item('Data Source').Value = $destinationPath
    $connection.Mode = 3
    $connection.Open()
    $external = $donorPath.Replace("'", "''")
    $row = $connection.Execute("SELECT THE_GUID FROM GUID_TRANSLATION IN '$external' WHERE OLD_CHEMCAD_ID=$ComponentId")
    if ($row.EOF) { throw 'Component absent from donor' }
    $guid = $row.Fields.Item('THE_GUID').Value
    $row.Close()
    [void]$connection.BeginTrans()
    try {
        foreach ($table in @('MAINDATA','GUID_TRANSLATION','LIBRARY','ATOMS','SYNONYM','EBIPS','OLD_COMPONENT_GROUP_DATA')) {
            $fields = $connection.Execute("SELECT TOP 1 * FROM [$table]")
            $sourceFields = $connection.Execute("SELECT TOP 1 * FROM [$table] IN '$external'")
            $sourceNames = @($sourceFields.Fields | ForEach-Object { $_.Name })
            $columns = ($fields.Fields | Where-Object { $sourceNames -contains $_.Name } | ForEach-Object { '[' + $_.Name + ']' }) -join ','
            $fields.Close()
            $sourceFields.Close()
            $guidColumn = if ($table -eq 'EBIPS') { 'GUID_COMPONENT' } else { 'THE_GUID' }
            $query = "INSERT INTO [$table] ($columns) SELECT $columns FROM [$table] IN '$external' WHERE [$guidColumn] = {guid $guid}"
            [void]$connection.Execute($query)
            Write-Output "Copied $table"
        }
        $connection.CommitTrans()
    } catch {
        $connection.RollbackTrans()
        throw
    }
} finally {
    if ($connection.State -ne 0) { $connection.Close() }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($connection)
}
