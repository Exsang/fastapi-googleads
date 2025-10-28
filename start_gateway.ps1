# start_gateway.ps1
# Starts FastAPI (APP) and ngrok, then prints your import URL

# Navigate to project directory
Set-Location "$env:USERPROFILE\Desktop\fastapi-googleads"

# Activate virtual environment
& "venv\Scripts\activate.ps1"

# Start Uvicorn in background
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'python -m uvicorn app.main:APP --reload' 

# Give Uvicorn a few seconds to boot
Start-Sleep -Seconds 5

# Start ngrok tunnel on port 8000
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'ngrok http 8000'

# Wait for ngrok to establish the tunnel and then fetch the URL
Start-Sleep -Seconds 5
try {
    $apiResponse = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels"
    $publicUrl = $apiResponse.tunnels[0].public_url
    Write-Host "`n✅ Your FastAPI is live!"
    Write-Host "👉 Import URL for GPT Actions:"
    Write-Host "$publicUrl/openapi.json`n"
} catch {
    Write-Host ⚠️ Could not fetch ngrok URL automatically. Open http://127.0.0.1:4040 to view it."
}
