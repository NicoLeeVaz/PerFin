# Local-only Excel COM smoke test. Does not enable macros or refresh queries.
# PerFin_SYNTHETIC_WORKBOOK and PerFin_EXCEL_EVIDENCE are supplied by the Python runner.
$ErrorActionPreference = 'Stop'
$excel = $null
$book = $null
$result = @{ status = 'FAIL'; scope = 'desktop Excel fixture open and recalculation only'; checks = @() }
try {
    $path = $env:PerFin_SYNTHETIC_WORKBOOK
    if (-not [IO.File]::Exists($path)) { throw 'Synthetic workbook missing' }
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AutomationSecurity = 3 # msoAutomationSecurityForceDisable
    $book = $excel.Workbooks.Open($path, 0, $true)
    $excel.CalculateFullRebuild()
    $result.excel_version = $excel.Version
    $expected = @{
        PerFin_TotalAssets = 13700.0
        PerFin_TotalOwed = 300005.0
        PerFin_NetBalance = -286305.0
        PerFin_CardsOwed = 605.0
        PerFin_TxnNet = 1645.0
    }
    foreach ($name in $expected.Keys) {
        $actual = [double]$book.Names.Item($name).RefersToRange.Value2
        $ok = [Math]::Abs($actual - $expected[$name]) -lt 0.0000001
        $result.checks += @{ check = $name; status = $(if ($ok) { 'PASS' } else { 'FAIL' }); actual = $actual; expected = $expected[$name] }
    }
    $result.status = $(if (@($result.checks | Where-Object { $_.status -ne 'PASS' }).Count -eq 0) { 'PASS' } else { 'FAIL' })
} catch {
    $result.error = $_.Exception.GetType().FullName
    $result.status = $(if ($null -eq $excel) { 'BLOCKED' } else { 'FAIL' })
} finally {
    if ($null -ne $book) { $book.Close($false); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($book) }
    if ($null -ne $excel) { $excel.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $env:PerFin_EXCEL_EVIDENCE
}
if ($result.status -eq 'PASS') { exit 0 } elseif ($result.status -eq 'BLOCKED') { exit 2 } else { exit 1 }
