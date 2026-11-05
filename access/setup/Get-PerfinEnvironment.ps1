<#
.SYNOPSIS
  PerFin environment check (PowerShell companion to `python -m perfin_store envcheck`).
  Local registry and ODBC queries only; makes no network calls. Not yet run on Windows [Unverified].

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File access\setup\Get-PerfinEnvironment.ps1
#>
$ErrorActionPreference = 'Continue'
$ace = 'Microsoft Access Driver (*.mdb, *.accdb)'
$report = [ordered]@{}
$report.windows = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture)
$report.powershell_is_64bit = [Environment]::Is64BitProcess

$c2r = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration' -ErrorAction SilentlyContinue
if ($c2r) {
  $report.office = [ordered]@{ platform = $c2r.Platform; version = $c2r.VersionToReport; products = $c2r.ProductReleaseIds }
} else {
  $report.office = 'Click-to-Run configuration not found (MSI Office or no Office)'
}
$report.access_exe = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MSACCESS.EXE'
$report.access_runtime_hint = [bool]($c2r -and ($c2r.ProductReleaseIds -match 'AccessRuntime'))

$drivers = @()
foreach ($platform in '32-bit', '64-bit') {
  $found = Get-OdbcDriver -Name 'Microsoft Access Driver*' -Platform $platform -ErrorAction SilentlyContinue
  foreach ($d in $found) { $drivers += "$($d.Name) [$platform]" }
}
$report.ace_odbc_drivers = $drivers
$report.ace_oledb = @('Microsoft.ACE.OLEDB.12.0', 'Microsoft.ACE.OLEDB.16.0') | Where-Object { Test-Path "Registry::HKEY_CLASSES_ROOT\$_" }

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
  $report.python = & py -3 -c "import platform,struct;print(platform.python_version(), struct.calcsize('P')*8, 'bit')"
}
$report.verdict = if ($drivers -match [regex]::Escape($ace)) { "ACE ODBC driver present; Python bitness must match the listed platform" } else { "ACE ODBC driver missing: install the Microsoft Access Database Engine matching Office bitness" }
$report | ConvertTo-Json -Depth 4
