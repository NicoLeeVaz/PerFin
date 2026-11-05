param([string]$DataRoot = "$env:LOCALAPPDATA\PerFin")
$ErrorActionPreference = 'Stop'
python -m perfin_app --data-root $DataRoot gui
if ($LASTEXITCODE -ne 0) { throw 'PerFin launcher failed; run perfin envcheck' }
