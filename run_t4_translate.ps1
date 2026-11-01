# T-4 Translate Sandbox Runner
# این اسکریپت PowerShell (.ps1) برای اجرای کامل پروژه در ویندوز/سیستم‌های سازگار طراحی شده است.
# توجه: در محیط فعلی (Arena Sandbox) سرورها از طریق ابزار start_process اجرا می‌شوند،
# اما این فایل برای استفاده شما و داداشتان در سیستم محلی (ویندوز) آماده شده است.

Write-Host "شروع اجرای پروژه T-4 Translate..." -ForegroundColor Cyan

# ۱. بررسی مسیر پروژه
$projectPath = "C:\T-4-Translate" # مسیر را در سیستم خود تنظیم کنید
if (-not (Test-Path $projectPath)) {
    Write-Host "خطا: مسیر پروژه یافت نشد: $projectPath" -ForegroundColor Red
    exit 1
}

Set-Location $projectPath

# ۲. اجرای بک‌اند (Python FastAPI)
Write-Host "در حال اجرا کردن بک‌اند (پورت ۸۰۰۰)..." -ForegroundColor Yellow
Start-Process python -ArgumentList "backend/app/main.py" -WindowStyle Hidden
Start-Sleep -Seconds 5

# ۳. اجرای فرانت‌اند (Vite/React)
Write-Host "در حال اجرا کردن فرانت‌اند (پورت ۵۱۷۳)..." -ForegroundColor Yellow
Start-Process npm -ArgumentList "run dev" -WorkingDirectory "$projectPath/frontend" -WindowStyle Hidden
Start-Sleep -Seconds 5

# ۴. باز کردن مرورگر
$url = "http://localhost:5173/"
Start-Process $url
Write-Host "پروژه اجرا شد! لینک: $url" -ForegroundColor Green

# برای متوقف کردن: در پنجره‌های باز شده Ctrl+C بزنید یا فرآیندها را ببندید.
Read-Host "برای پایان کار هر کلیدی را بفشارید..."
