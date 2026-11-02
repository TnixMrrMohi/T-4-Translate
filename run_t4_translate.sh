#!/usr/bin/env bash
# T-4 Translate - اجراکنندهٔ محلی برای لینوکس و macOS
#
# استفاده:
#   ./run_t4_translate.sh              # نصب خودکار در بار اول و اجرا
#   ./run_t4_translate.sh --install-ocr
#   BACKEND_PORT=8010 FRONTEND_PORT=5180 ./run_t4_translate.sh
#
# بک‌اند روی 127.0.0.1:8000 و رابط Vite روی 127.0.0.1:5173 بالا می‌آید.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
VENV_PY="$VENV/bin/python"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
INSTALL_OCR=0

for arg in "$@"; do
  case "$arg" in
    --install-ocr) INSTALL_OCR=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "گزینهٔ ناشناخته: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33mهشدار: %s\033[0m\n' "$1" >&2; }
fail() { printf '\033[31mخطا: %s\033[0m\n' "$1" >&2; exit 1; }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
wait_port() {
  local port=$1 seconds=$2 name=$3 waited=0
  while [ "$waited" -lt "$seconds" ]; do
    if port_busy "$port"; then return 0; fi
    sleep 0.4; waited=$((waited + 1))
  done
  warn "$name در $seconds ثانیه بالا نیامد."
  return 1
}

# ------------------------------------------------------------- پیش‌نیازها
step "بررسی پیش‌نیازها"
command -v python3 >/dev/null 2>&1 || fail "python3 پیدا نشد. Python 3.11+ نصب کنید."
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11+ لازم است (نسخهٔ فعلی: $(python3 -c 'import sys;print(sys.version.split()[0])'))"
command -v node >/dev/null 2>&1 || fail "Node.js پیدا نشد. نسخهٔ ۲۰ LTS را نصب کنید."
command -v npm  >/dev/null 2>&1 || fail "npm پیدا نشد؛ نصب Node.js را بررسی کنید."
port_busy "$BACKEND_PORT"  && fail "پورت $BACKEND_PORT (بک‌اند) اشغال است."
port_busy "$FRONTEND_PORT" && fail "پورت $FRONTEND_PORT (فرانت‌اند) اشغال است."

# ------------------------------------------------------------- محیط مجازی
if [ ! -x "$VENV_PY" ]; then
  step "ساخت محیط مجازی پایتون (backend/.venv)"
  python3 -m venv "$VENV"
fi

step "بررسی وابستگی‌های بک‌اند"
if ! "$VENV_PY" -c 'import fastapi, uvicorn, PIL, multipart, arabic_reshaper, bidi' >/dev/null 2>&1; then
  step "نصب وابستگی‌های بک‌اند (چند دقیقه طول می‌کشد)"
  ( cd "$BACKEND" && "$VENV_PY" -m pip install --upgrade pip --quiet && "$VENV_PY" -m pip install -e '.[test,render]' )
fi

if [ "$INSTALL_OCR" = "1" ]; then
  if ! "$VENV_PY" -c 'import rapidocr_onnxruntime, cv2, numpy' >/dev/null 2>&1; then
    step "نصب OCR آزمایشی (RapidOCR؛ حجم زیاد)"
    ( cd "$BACKEND" && "$VENV_PY" -m pip install -e '.[ocr-experimental]' ) || warn "نصب OCR ناموفق بود."
  fi
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  step "نصب بسته‌های فرانت‌اند (npm ci)"
  ( cd "$FRONTEND" && npm ci --no-audit --no-fund )
fi

# ------------------------------------------------------------- اجرا
BACKEND_PID=""
FRONTEND_PID=""
CLEANED=0
cleanup() {
  [ "$CLEANED" = "1" ] && return
  CLEANED=1
  step "خاموش کردن سرویس‌ها"
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

step "اجرای بک‌اند روی http://127.0.0.1:$BACKEND_PORT"
( cd "$BACKEND" && exec "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" ) &
BACKEND_PID=$!
wait_port "$BACKEND_PORT" 150 "بک‌اند" || fail "بک‌اند اجرا نشد. اجرای دستی: cd backend && .venv/bin/python -m uvicorn app.main:app"
echo "    بک‌اند سالم است (/healthz)."

step "اجرای رابط روی http://127.0.0.1:$FRONTEND_PORT"
( cd "$FRONTEND" && exec env T4_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT" --strictPort ) &
FRONTEND_PID=$!
wait_port "$FRONTEND_PORT" 225 "فرانت‌اند" || fail "فرانت‌اند اجرا نشد. اجرای دستی: cd frontend && npm run dev"

echo
echo "پروژه بالا آمد:"
echo "  رابط کاربری : http://127.0.0.1:$FRONTEND_PORT/"
echo "  بک‌اند      : http://127.0.0.1:$BACKEND_PORT/healthz"
echo "  داده‌ها      : ${T4_DATA_DIR:-$HOME/.t4-translate}"
echo
echo "برای خاموش کردن، Ctrl+C بزنید."
wait
