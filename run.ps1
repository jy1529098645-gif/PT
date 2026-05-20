# Highlight Recovery — PowerShell launcher
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$py = (Get-Command py -ErrorAction SilentlyContinue) ?
      'py -3' : 'python'
if ($null -eq $py -or $py -eq '') { $py = 'python' }

Write-Host "Installing / verifying dependencies..." -ForegroundColor Cyan
& $py -m pip install -q -r requirements.txt

Write-Host ""
Write-Host "Launching app at http://127.0.0.1:8123" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""
Start-Process 'http://127.0.0.1:8123/'
& $py -m uvicorn backend.main:app --host 127.0.0.1 --port 8123
