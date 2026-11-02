"""Windows desktop host. A loopback server is shared only with this window.

برنامه به‌صورت بستهٔ PyInstaller (onedir) اجرا می‌شود: فایل‌های همراه (رابط ساخته‌شده
و فونت‌ها) در `_MEIPASS` هستند. اگر پنجرهٔ بومی (WebView2) به هر دلیلی بالا نیاید،
همان سرور محلی در مرورگر پیش‌فرض باز می‌شود تا کاربر بدون برنامه نماند.
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _base() -> Path:
    """ریشهٔ فایل‌های همراه: در بستهٔ PyInstaller پوشهٔ `_MEIPASS`، وگرنه ریشهٔ مخزن."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _log(message: str) -> None:
    # پیام‌ها انگلیسی‌اند تا در کنسول ویندوز (cp1252) به‌هم نریزند.
    print(message, flush=True)


def _smoke_test(url: str) -> None:
    """بررسی سالم بودن بستهٔ ساخته‌شده: سرور، رابط، مدل OCR، فونت‌ها و رندر فارسی."""
    with urllib.request.urlopen(url + "/healthz", timeout=5) as response:
        assert response.read() == b"ok"
    with urllib.request.urlopen(url + "/", timeout=5) as response:
        assert b'<div id="root">' in response.read()

    from app import fonts, rendering
    from app.ocr import _engine, recognize
    from PIL import Image
    import tempfile

    _engine()
    with tempfile.TemporaryDirectory() as directory:
        image_path = Path(directory) / "smoke.png"
        Image.new("RGB", (64, 64), "white").save(image_path)
        recognize(image_path)

    directories = fonts.bundled_dirs()
    assert directories, "no bundled font directories were found"
    image = Image.new("RGB", (260, 130), "white")
    blocks = [{"number": 1, "lines": [1], "bbox": [10, 10, 250, 120], "kind": "speech", "fill": 1.0}]
    canvas, drawn = rendering.render_blocks(image, blocks, {"1": "سلام دنیا، این یک آزمایش است."}, {})
    assert drawn == 1
    log = f"[T4] smoke test ok: fonts={len(fonts.list_fonts())} dirs={len(directories)}"
    _log(log)


def _browser_fallback(url: str) -> None:
    _log(f"[T4] Open this address in your browser: {url}")
    try:
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover - محیط بدون مرورگر
        _log(f"[T4] could not open a browser automatically ({exc})")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


def main():
    base = _base()
    os.environ["T4_DESKTOP"] = "1"
    os.environ["T4_WEB_DIR"] = str(base / "web")
    if "T4_DATA_DIR" not in os.environ:
        os.environ["T4_DATA_DIR"] = str(
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "T4Translate"
        )

    import uvicorn
    from app.main import app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Local server failed to start")
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("Local server startup timed out")
        if "--smoke-test" in sys.argv:
            _smoke_test(url)
            return
        _log(f"[T4] data: {os.environ['T4_DATA_DIR']}")
        _log(f"[T4] server: {url}")
        try:
            import webview
        except Exception as exc:
            _log(f"[T4] window support unavailable ({exc}); using the browser")
            _browser_fallback(url)
            return
        try:
            webview.create_window("T-4 Translate", url, width=1200, height=820,
                                  min_size=(720, 560))
            webview.start()
        except Exception as exc:
            _log(f"[T4] window failed ({exc}); using the browser")
            _browser_fallback(url)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


if __name__ == "__main__":
    main()
