# T-4 Translate Sandbox Runner
# این اسکریپت PowerShell (.ps1) برای اجرای کامل پروژه در ویندوز/سیستم‌های سازگار طراحی شده است.
# مسیر پروژه به صورت پویا (محل قرارگیری اسکریپت) تنظیم شده است.

Write-Host "شروع اجرای پروژه T-4 Translate..." -ForegroundColor Cyan

# ۱. تعیین مسیر پروژه (محل قرارگیری اسکریپت)
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path $projectPath)) {
    Write-Host "خطا: مسیر پروژه یافت نشد: $projectPath" -ForegroundColor Red
    exit 1
}

Set-Location $projectPath

# ۲. اجرای بک‌اند (Python FastAPI)
Write-Host "در حال اجرا کردن بک‌اند (پورت ۸۰۰۰)..." -ForegroundColor Yellow
# استفاده از Start-Process با -WindowStyle Hidden اما با نگه داشتن فرآیند
Start-Process python -ArgumentList "backend/app/main.py" -WindowStyle Hidden -PassThru | Out-Null
Start-Sleep -Seconds 5

# ۳. اجرای فرانت‌اند (Vite/React)
Write-Host "در حال اجرا کردن فرانت‌اند (پورت ۵۱۷۳)..." -ForegroundColor Yellow
Start-Process npm -ArgumentList "run dev" -WorkingDirectory "$projectPath/frontend" -WindowStyle Hidden -PassThru | Out-Null
Start-Sleep -Seconds 5

# ۴. باز کردن مرورگر
$url = "http://localhost:5173/"
Start-Process $url
Write-Host "پروژه اجرا شد! لینک: $url" -ForegroundColor Green

# ۵. نگه داشتن پنجره باز (مهم برای جلوگیری از بسته شدن)
Write-Host "برای توقف سرورها و بستن پنجره، هر کلیدی را بفشارید..." -ForegroundColor Yellow
$null = Read-Host

# توقف فرآیندها (اختیاری - اگر می‌خواهید پس از بستن اسکریپت سرورها متوقف شوند)
# Get-Process python | Stop-Process -Force
# Get-Process node | Stop-Process -Force
