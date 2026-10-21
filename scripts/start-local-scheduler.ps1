# Use only on the chosen host, which must stay awake and online for the full window.
$ErrorActionPreference='Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PREFECT_HOME = Join-Path $projectRoot '.prefect'
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
$logDir = Join-Path $projectRoot 'work\operations'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
try { Invoke-RestMethod 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null }
catch {
    $serverProcess = Start-Process -FilePath $projectPython -ArgumentList '-m prefect server start --host 127.0.0.1' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'server.out.log') -RedirectStandardError (Join-Path $logDir 'server.err.log')
    $serverProcess.Id | Set-Content (Join-Path $logDir 'server.pid')
    $ready=$false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        try { Invoke-RestMethod 'http://127.0.0.1:4200/api/health' -TimeoutSec 2 | Out-Null; $ready=$true; break } catch {}
    }
    if (-not $ready) { throw 'Prefect server did not become healthy; inspect logs.' }
}
$runnerProcess = Start-Process -FilePath $projectPython -ArgumentList '-m saayashift.flow --serve' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'runner.out.log') -RedirectStandardError (Join-Path $logDir 'runner.err.log')
$runnerProcess.Id | Set-Content (Join-Path $logDir 'runner.pid')
Write-Host 'Runner started. Check Prefect at http://127.0.0.1:4200 and verify a real completed run. The runner inhibits idle sleep. Keep power and internet connected; restarts and closing the laptop can still interrupt it.'
