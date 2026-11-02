$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProjectRoot
if (-not (Test-Path -LiteralPath '.env')) { python scripts/init_env.py }
if (-not (Test-Path -LiteralPath 'frontend/node_modules')) {
    Push-Location -LiteralPath frontend
    npm.cmd ci
    Pop-Location
}
$taskBackend = Start-Process -FilePath python -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $taskProjectRoot -WindowStyle Hidden -PassThru
$taskFrontend = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm.cmd run dev -- --port 5173 --strictPort' -WorkingDirectory (Join-Path $taskProjectRoot 'frontend') -WindowStyle Hidden -PassThru
Write-Host "EmoTherm: http://localhost:5173"
Write-Host "API docs: http://localhost:8000/docs"
Write-Host "Backend PID: $($taskBackend.Id); frontend PID: $($taskFrontend.Id). Stop these processes when finished."
