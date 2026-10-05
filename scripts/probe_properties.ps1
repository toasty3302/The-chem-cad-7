param([Parameter(Mandatory=$true)][string]$DatabasePath)
$ErrorActionPreference = 'Stop'
$connection = New-Object -ComObject ADODB.Connection
try {
    $connection.Provider = 'Microsoft.Jet.OLEDB.4.0'
    $connection.Properties.Item('Data Source').Value = (Resolve-Path -LiteralPath $DatabasePath).Path
    $connection.Mode = 1
    $connection.Open()
    $tables = $connection.OpenSchema(20)
    while (-not $tables.EOF) {
        if ($tables.Fields.Item('TABLE_TYPE').Value -eq 'TABLE') {
            $name = $tables.Fields.Item('TABLE_NAME').Value
            Write-Output "TABLE $name"
            $rows = $connection.Execute(('SELECT TOP 1 * FROM [' + $name.Replace(']', ']]') + ']'))
            foreach ($field in $rows.Fields) {
                $value = if ($rows.EOF) { '<empty>' } else { $field.Value }
                if ($value -is [System.Array]) { $value = '<binary>' }
                Write-Output ("  {0} type={1} value={2}" -f $field.Name,$field.Type,$value)
            }
            $rows.Close()
        }
        $tables.MoveNext()
    }
    $tables.Close()
} finally {
    if ($connection.State -ne 0) { $connection.Close() }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($connection)
}
