# ==============================
#  test_gateway.ps1  (v2)
#  Uses Invoke-RestMethod to auto-parse JSON
# ==============================

param(
    [string]$BaseUrl = "https://linh-chapeless-mercilessly.ngrok-free.dev",
    [string]$ApiKey  = "YOUR_DASH_API_KEY"
)

# Ensure TLS 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Headers = @{ Authorization = "Bearer $ApiKey" }

function Hit($path) {
    $url = "$BaseUrl$path"
    Write-Host "----------------------------------------"
    Write-Host "GET $path" -ForegroundColor Cyan
    try {
        $json = Invoke-RestMethod -Uri $url -Headers $Headers -Method GET
        Write-Host "✅ Success"
        $json | ConvertTo-Json -Depth 6 | Write-Host
    } catch {
        Write-Host "❌ Error: $($_.Exception.Message)" -ForegroundColor Red
        # show raw body if available
        if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
            $reader = New-Object System.IO.StreamReader $_.Exception.Response.GetResponseStream()
            $body = $reader.ReadToEnd()
            Write-Host "Raw response:" -ForegroundColor Yellow
            Write-Host $body
        }
    }
}

Write-Host "`n=== Testing FastAPI Gateway ==="
Write-Host "Base URL: $BaseUrl"
Write-Host "================================`n"

Hit "/health"
Hit "/ads/usage-summary"
Hit "/ads/active-accounts?mcc_id=7414394764"

Write-Host "`nDone.`n"
