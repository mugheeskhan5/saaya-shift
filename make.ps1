param(
    [ValidateSet('data','evaluate','verify')][string]$Target='data',
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$PipelineArgs
)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Create .venv and install requirements-pipeline.txt first; see README.md.' }
& $projectPython -m saayashift.cli $Target @PipelineArgs
exit $LASTEXITCODE
