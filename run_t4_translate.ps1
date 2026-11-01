#Requires -Version 5.1
<#
    T-4 Translate - اجراکنندهٔ محلی برای ویندوز

    چه کاری انجام می‌دهد؟
      ۱. بررسی نصب بودن Python 3.11+ و Node.js
      ۲. ساخت محیط مجازی backend/.venv و نصب وابستگی‌های بک‌اند (فقط بار اول)
      ۳. نصب بسته‌های فرانت‌اند با npm ci (فقط بار اول)
      ۴. اجرای بک‌اند روی 127.0.0.1:8000 و رابط Vite روی 127.0.0.1:5173
      ۵. باز کردن مرورگر و خاموش کردن هر دو سرویس با Enter

    نمونهٔ استفاده:
      powershell -ExecutionPolicy Bypass -File .\run_t4_translate.ps1
      powershell -ExecutionPolicy Bypass -File .\run_t4_translate.ps1 -InstallOcr
      powershell -ExecutionPolicy Bypass -File .\run_t4_translate.ps1 -BackendPort 8010 -FrontendPort 5180
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$InstallOcr,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv     = Join-Path $backend '.venv'
$venvPy   = Join-Path $venv 'Scripts\python.exe'

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "هشدار: $message" -ForegroundColor Yellow }
function Fail($message) {
    Write-Host "خطا: $message" -ForegroundColor Red
    exit 1
}

function Test-PortInUse([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(400)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Port([int]$port, [int]$seconds, [string]$name) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortInUse $port) { return $true }
        Start-Sleep -Milliseconds 400
    }
    Write-Warn "$name در $seconds ثانیه بالا نیامد."
    return $false
}

function Stop-Tree($process) {
    if ($null -eq $process) { return }
    if ($process.HasExited) { return }
    & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
}

# ---------------------------------------------------------------- پیش‌نیازها
Write-Step "بررسی پیش‌نیازها"

$pythonExe  = $null
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    # «py» مطمئن‌ترین راه روی ویندوز است و نسخهٔ نصب‌شده را انتخاب می‌کند.
    $pythonExe = 'py'
    $pythonArgs = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = 'python'
}
if (-not $pythonExe) {
    Fail "Python پیدا نشد. Python 3.11 یا جدیدتر را از https://www.python.org/downloads/windows/ نصب کنید و گزینهٔ Add to PATH را بزنید."
}

$pyOk = & $pythonExe @pythonArgs -c "import sys; print(1 if sys.version_info >= (3, 11) else 0)" 2>$null
if ($pyOk -ne '1') {
    $found = (& $pythonExe @pythonArgs -c "import sys; print(sys.version.split()[0])" 2>$null)
    Fail "Python 3.11+ لازم است (نسخهٔ پیدا‌شده: $found)."
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node.js پیدا نشد. نسخهٔ ۲۰ LTS را از https://nodejs.org نصب کنید."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "npm پیدا نشد؛ نصب Node.js را بررسی کنید."
}
Write-Host "    Python و Node.js آماده‌اند."

foreach ($pair in @(@{Port = $BackendPort; Name = 'بک‌اند' }, @{Port = $FrontendPort; Name = 'فرانت‌اند' })) {
    if (Test-PortInUse $pair.Port) {
        Fail "پورت $($pair.Port) ($($pair.Name)) اشغال است. برنامهٔ دیگری را ببندید یا با -BackendPort/-FrontendPort پورت دیگر بدهید."
    }
}

# ---------------------------------------------------------------- محیط مجازی
if (-not (Test-Path $venvPy)) {
    Write-Step "ساخت محیط مجازی پایتون (backend\.venv)"
    & $pythonExe @pythonArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fail "ساخت محیط مجازی ناموفق بود." }
}

Write-Step "بررسی وابستگی‌های بک‌اند"
& $venvPy -c "import fastapi, uvicorn, PIL, multipart" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "نصب وابستگی‌های بک‌اند (چند دقیقه طول می‌کشد)"
    Push-Location $backend
    try {
        & $venvPy -m pip install --upgrade pip --quiet
        & $venvPy -m pip install -e ".[test]"
        if ($LASTEXITCODE -ne 0) { Fail "نصب وابستگی‌های بک‌اند ناموفق بود." }
    } finally {
        Pop-Location
    }
}

if ($InstallOcr) {
    & $venvPy -c "import rapidocr_onnxruntime, cv2, numpy" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "نصب OCR آزمایشی (RapidOCR؛ حجم زیاد، چند دقیقه)"
        Push-Location $backend
        try {
            & $venvPy -m pip install -e ".[ocr-experimental]"
            if ($LASTEXITCODE -ne 0) { Write-Warn "نصب OCR ناموفق بود؛ برنامه بدون OCR اجرا می‌شود." }
        } finally {
            Pop-Location
        }
    }
}

# ---------------------------------------------------------------- فرانت‌اند
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Step "نصب بسته‌های فرانت‌اند (npm ci)"
    Push-Location $frontend
    try {
        & npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Fail "npm ci ناموفق بود." }
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------- اجرا
$backendProc  = $null
$frontendProc = $null

try {
    Write-Step "اجرای بک‌اند روی http://127.0.0.1:$BackendPort"
    $backendProc = Start-Process -FilePath $venvPy `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
        -WorkingDirectory $backend -PassThru -WindowStyle Hidden

    if (-not (Wait-Port $BackendPort 60 'بک‌اند')) {
        Fail "بک‌اند اجرا نشد. اجرای دستی برای دیدن خطا: cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port $BackendPort"
    }

    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/healthz" -UseBasicParsing -TimeoutSec 5
        if ($health.Content.Trim() -ne 'ok') { Write-Warn "پاسخ /healthz غیرمنتظره بود: $($health.Content)" }
    } catch {
        Write-Warn "درخواست /healthz ناموفق بود: $($_.Exception.Message)"
    }
    Write-Host "    بک‌اند سالم است (/healthz)."

    Write-Step "اجرای رابط روی http://127.0.0.1:$FrontendPort"
    # پروکسی Vite باید همان پورتی را هدف بگیرد که بک‌اند روی آن اجرا شده است.
    $env:T4_BACKEND_URL = "http://127.0.0.1:$BackendPort"
    $frontendProc = Start-Process -FilePath $env:ComSpec `
        -ArgumentList @('/c', "npm run dev -- --port $FrontendPort --strictPort") `
        -WorkingDirectory $frontend -PassThru -WindowStyle Hidden

    if (-not (Wait-Port $FrontendPort 90 'فرانت‌اند')) {
        Fail "فرانت‌اند اجرا نشد. اجرای دستی برای دیدن خطا: cd frontend; npm run dev"
    }

    $url = "http://127.0.0.1:$FrontendPort/"
    if (-not $NoBrowser) { Start-Process $url }
    Write-Host ""
    Write-Host "پروژه بالا آمد:" -ForegroundColor Green
    Write-Host "  رابط کاربری : $url"
    Write-Host "  بک‌اند      : http://127.0.0.1:$BackendPort/healthz"
    Write-Host "  داده‌ها      : $env:USERPROFILE\.t4-translate (قابل تغییر با T4_DATA_DIR)"
    Write-Host ""
    Write-Host "برای خاموش کردن هر دو سرویس، Enter بزنید..." -ForegroundColor Yellow
    [void](Read-Host)
} finally {
    Write-Step "خاموش کردن سرویس‌ها"
    Stop-Tree $frontendProc
    Stop-Tree $backendProc
}
