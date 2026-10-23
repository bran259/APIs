param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Project Python environment not found. From the project folder, run: py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

$envCheck = "from dotenv import load_dotenv; import os, sys; load_dotenv(); url=os.getenv('SUPABASE_URL', ''); key=os.getenv('SUPABASE_KEY', ''); sys.exit(0 if url and key and 'your-project' not in url and 'your-supabase' not in key else 1)"
& $python -c $envCheck
if ($LASTEXITCODE -ne 0) {
    Write-Error "SUPABASE_URL or SUPABASE_KEY is missing or still has the example value. Set both in .env or your environment, then run this script again."
    exit 1
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start()
    $listener.Stop()
}
catch {
    $listener.Stop()
    $existingPage = $null
    $probeFailure = $null
    try {
        $existingPage = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
    }
    catch {
        $probeFailure = $_.Exception.Message
    }
    if ($existingPage -and $existingPage.StatusCode -eq 200 -and $existingPage.Content -match "<title>Things") {
        Write-Host "The Things app is already running at http://127.0.0.1:$Port/."
        Write-Host "Open that address in your browser; no second server is needed."
        exit 0
    }
    if ($probeFailure) {
        Write-Error "Port $Port is already in use, but the frontend check failed: $probeFailure. Run .\run_frontend.ps1 -Port 8765 to use another port."
        exit 1
    }
    Write-Error "Port $Port is already in use. Stop the existing app or run this script with another port, for example: .\run_frontend.ps1 -Port 8765"
    exit 1
}

Write-Host "Starting the Things app at http://127.0.0.1:$Port/"
Write-Host "Leave this window open while using the app. Press Ctrl+C to stop it."
& $python -m uvicorn main:app --reload --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
