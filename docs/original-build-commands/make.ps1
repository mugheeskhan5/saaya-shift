param([ValidateSet('data','evaluate','test','dashboard','verify')][string]$Target='data')
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Install requirements in .venv first; see README.' }
switch ($Target) {
    'test' { & $projectPython -m pytest -q }
    'dashboard' { & $projectPython -m streamlit run app.py }
    default { & $projectPython -m saayashift.cli $Target }
}
exit $LASTEXITCODE
