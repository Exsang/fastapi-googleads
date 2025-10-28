# Stops FastAPI + ngrok processes that were started with start_gateway.ps1
$Proj = "$env:USERPROFILE\Desktop\fastapi-googleads"
$PidFile = Join-Path $Proj ".gateway_pids.json"

if (!(Test-Path $PidFile)) {
    Write-Host "No PID file found at $PidFile. Attempting generic shutdown..." -ForegroundColor Yellow
    taskkill /IM ngrok.exe /F 2>$null | Out-Null
    taskkill /IM python.exe /F 2>$null | Out-Null
    exit 0
}

try {
    $info = Get-Content $PidFile | ConvertFrom-Json
    if ($info.ngrokPid) {
        Write-Host "Stopping ngrok PID $($info.ngrokPid)..."
        Stop-Process -Id $info.ngrokPid -Force -ErrorAction SilentlyContinue
    } else {
        taskkill /IM ngrok.exe /F 2>$null | Out-Null
    }

    if ($info.fastapiPid) {
        Write-Host "Stopping FastAPI PID $($info.fastapiPid)..."
        Stop-Process -Id $info.fastapiPid -Force -ErrorAction SilentlyContinue
    } else {
        taskkill /IM python.exe /F 2>$null | Out-Null
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "✅ Stopped and cleaned up."
} catch {
    Write-Host "⚠️ Error reading PID file; best-effort cleanup..." -ForegroundColor Yellow
    taskkill /IM ngrok.exe /F 2>$null | Out-Null
    taskkill /IM python.exe /F 2>$null | Out-Null
}
