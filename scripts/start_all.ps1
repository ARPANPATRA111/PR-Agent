# Weekly Progress Agent - Startup Script
# Run this script to start all components with auto webhook setup

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Weekly Progress Agent - Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Determine project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
if (-not $ProjectRoot -or -not (Test-Path $ProjectRoot)) {
    $ProjectRoot = "b:\Public Repository\weekly_agent"
}

Write-Host "Project Root: $ProjectRoot" -ForegroundColor Yellow
Write-Host ""

# Check if ngrok is installed
$ngrokPath = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokPath) {
    Write-Host "ERROR: ngrok not found! Please install ngrok first." -ForegroundColor Red
    Write-Host "  Download from: https://ngrok.com/download" -ForegroundColor Yellow
    exit 1
}

# Step 1: Start ngrok in background
Write-Host "[1/5] Starting ngrok..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "ngrok http 8000"
Write-Host "       Waiting for ngrok to initialize..." -ForegroundColor Gray

# Wait for ngrok to start and get the URL
$maxAttempts = 15
$attempt = 0
$ngrokUrl = $null

while ($attempt -lt $maxAttempts -and -not $ngrokUrl) {
    Start-Sleep -Seconds 2
    $attempt++
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction SilentlyContinue
        $ngrokUrl = ($response.tunnels | Where-Object { $_.proto -eq "https" }).public_url
        if ($ngrokUrl) {
            Write-Host "       Ngrok URL: $ngrokUrl" -ForegroundColor Green
        }
    } catch {
        Write-Host "       Attempt $attempt/$maxAttempts - waiting for ngrok..." -ForegroundColor Gray
    }
}

if (-not $ngrokUrl) {
    Write-Host "WARNING: Could not auto-detect ngrok URL." -ForegroundColor Yellow
    Write-Host "         You'll need to set webhook manually." -ForegroundColor Yellow
}

Write-Host ""

# Step 2: Start Backend
Write-Host "[2/5] Starting Backend Server..." -ForegroundColor Green
$backendCmd = @"
cd '$ProjectRoot\backend'
if (Test-Path '.\venv\Scripts\Activate.ps1') {
    .\venv\Scripts\Activate.ps1
} else {
    Write-Host 'Creating virtual environment...' -ForegroundColor Yellow
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
}
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

# Wait for backend to start
Write-Host "       Waiting for backend to start..." -ForegroundColor Gray
$backendReady = $false
$attempt = 0
while ($attempt -lt 20 -and -not $backendReady) {
    Start-Sleep -Seconds 2
    $attempt++
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -ErrorAction SilentlyContinue
        if ($health) {
            $backendReady = $true
            Write-Host "       Backend is ready!" -ForegroundColor Green
        }
    } catch {
        Write-Host "       Attempt $attempt/20 - waiting for backend..." -ForegroundColor Gray
    }
}

if (-not $backendReady) {
    Write-Host "WARNING: Backend health check timed out." -ForegroundColor Yellow
}

Write-Host ""

# Step 3: Start Frontend  
Write-Host "[3/5] Starting Frontend..." -ForegroundColor Green
$frontendCmd = @"
cd '$ProjectRoot\frontend'
if (-not (Test-Path 'node_modules')) {
    Write-Host 'Installing frontend dependencies...' -ForegroundColor Yellow
    pnpm install
}
pnpm run dev
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Start-Sleep -Seconds 3
Write-Host ""

# Step 4: Set Webhook (if ngrok URL was detected)
if ($ngrokUrl) {
    Write-Host "[4/5] Setting Telegram webhook..." -ForegroundColor Green
    
    # Activate venv and run webhook setup
    $webhookCmd = @"
cd '$ProjectRoot\backend'
.\venv\Scripts\Activate.ps1
python ../scripts/setup_webhook.py '$ngrokUrl'
"@
    
    # Run webhook setup in current session (blocking)
    try {
        Push-Location "$ProjectRoot\backend"
        & .\venv\Scripts\Activate.ps1
        python ../scripts/setup_webhook.py $ngrokUrl
        Pop-Location
        Write-Host "       Webhook set successfully!" -ForegroundColor Green
    } catch {
        Write-Host "       Failed to set webhook: $_" -ForegroundColor Red
        Write-Host "       Run manually: python scripts/setup_webhook.py $ngrokUrl" -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/5] Skipping webhook setup (no ngrok URL)" -ForegroundColor Yellow
    Write-Host "       Set manually after ngrok starts." -ForegroundColor Gray
}

Write-Host ""

# Step 5: Summary
Write-Host "[5/5] Startup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  All Services Running!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Services:" -ForegroundColor Yellow
Write-Host "  - Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  - Frontend: http://localhost:3000" -ForegroundColor White
if ($ngrokUrl) {
    Write-Host "  - Ngrok:    $ngrokUrl" -ForegroundColor White
    Write-Host "  - Webhook:  Configured!" -ForegroundColor Green
} else {
    Write-Host "  - Ngrok:    Check ngrok window for URL" -ForegroundColor Yellow
    Write-Host "  - Webhook:  Manual setup needed" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Telegram Bot: Search @YourBot on Telegram" -ForegroundColor Cyan
Write-Host "Dashboard:    http://localhost:3000" -ForegroundColor Cyan
Write-Host ""

# If webhook wasn't set, provide manual instructions
if (-not $ngrokUrl) {
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Manual Webhook Setup" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "After ngrok shows its URL, run:" -ForegroundColor White
    Write-Host ""
    Write-Host "  cd `"$ProjectRoot\backend`"" -ForegroundColor Gray
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host "  python ../scripts/setup_webhook.py https://YOUR-NGROK-URL.ngrok-free.dev" -ForegroundColor Gray
    Write-Host ""
}
