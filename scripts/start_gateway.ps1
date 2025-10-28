# scripts/start_gateway.ps1
<# 
Purpose: Verify env, start FastAPI (APP) + ngrok, then print import URL & open docs.
Run: powershell -ExecutionPolicy Bypass -File .\scripts\start_gateway.ps1
#>

$ErrorActionPreference = "Stop"

# --- Basics ---
$RepoRoot = "$env:USERPROFILE\Desktop\fastapi-googleads"
$VenvAct  = Join-Path $RepoRoot "venv\Scripts\Activate.ps1"
$HostIp   = "127.0.0.1"
$Port     = 8000
$NgrokAPI = "http://127.0.0.1:4040/api/tunnels"

# --- Helpers ---
function Test-AppUp {
  try {
    $r = Invoke-WebRequest -Uri "http://$HostIp:$Port/health" -UseBasicParsing -TimeoutSec 2
    return $r.StatusCode -eq 200
  } catch { return $false }
}

function Get-NgrokUrl {
  try {
    $res = Invoke-RestMethod -Uri $NgrokAPI -TimeoutSec 2
    $https = $res.tunnels | Where-Object { $_.public_url -like "https://*" }
    if ($https) { return $https[0].public_url }
    return $null
  } catch { return $null }
}

Write-Host "`n=== Google Ads Gateway: start ===`n"

# 0) cd & venv
if (-not (Test-Path $RepoRoot)) { throw "Repo not found at $RepoRoot" }
Set-Location $RepoRoot
if (-not (Test-Path $VenvAct)) { throw "Virtual env not found: $VenvAct" }
. $VenvAct
Write-Host "✅ Virtual env activated"

# 1) Start FastAPI if needed
if (Test-AppUp) {
  Write-Host "✅ FastAPI already running on http://$HostIp:$Port"
} else {
  Write-Host "🚀 Starting FastAPI (uvicorn app.main:APP --reload)..."
  Start-Process -WindowStyle Hidden -FilePath "python" -ArgumentList @(
    "-m","uvicorn","app.main:APP","--reload","--host",$HostIp,"--port",$Port
  ) | Out-Null

  # Wait for readiness (max ~10s)
  $tries = 0
  while (-not (Test-AppUp) -and $tries -lt 20) {
    Start-Sleep -Milliseconds 500
    $tries++
  }
  if (Test-AppUp) {
    Write-Host "✅ FastAPI is up at http://$HostIp:$Port"
  } else {
    throw "FastAPI did not start on port $Port — check your terminal logs."
  }
}

# 2) Start ngrok if needed
$PublicUrl = Get-NgrokUrl
if ($null -ne $PublicUrl) {
  Write-Host "✅ ngrok already running: $PublicUrl"
} else {
  Write-Host "🌐 Starting ngrok http $Port ..."
  Start-Process -WindowStyle Hidden -FilePath "ngrok" -ArgumentList @("http",$Port) | Out-Null

  # Wait for tunnel (max ~8s)
  $tries = 0
  while (-not $PublicUrl -and $tries -lt 16) {
    Start-Sleep -Milliseconds 500
    $PublicUrl = Get-NgrokUrl
    $tries++
  }
  if ($null -eq $PublicUrl) {
    Write-Host "⚠️  Could not fetch ngrok URL automatically. Open http://127.0.0.1:4040 to view tunnels."
  } else {
    Write-Host "✅ ngrok tunnel: $PublicUrl"
  }
}

# 3) Print import URLs and open docs
Write-Host "`n✅ Your FastAPI is live!"
Write-Host "👉 Local docs:  http://$HostIp:$Port/docs"
if ($PublicUrl) {
  Write-Host "👉 Public docs: $PublicUrl/docs"
  Write-Host "👉 Import URL for GPT Actions / OpenAPI:"
  Write-Host "   $PublicUrl/openapi.json`n"
  Start-Process "$PublicUrl/docs"
}
Start-Process "http://$HostIp:$Port/docs"

Write-Host "=== Done ===`n"
