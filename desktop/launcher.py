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


def _browser_fallback(url: str, stop: "threading.Event | None" = None) -> None:
    _log(f"[T4] Open this address in your browser: {url}")
    try:
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover - محیط بدون مرورگر
        _log(f"[T4] could not open a browser automatically ({exc})")
    try:
        while True:
            if stop is not None and stop.is_set():
                return
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


def _apply_ready_update_on_start() -> bool:
    """اگر آپدیت دانلودشده‌ای منتظر است، پیش از بالا آمدن برنامه اعمال می‌شود.

    فایل `T4Translate.exe` در حال اجرا قابل جایگزینی نیست؛ پس اسکریپت اعمال را
    جدا اجرا می‌کنیم و همین فرایند بلافاصله خارج می‌شود تا فایل آزاد شود.
    """
    try:
        from app import updater
    except Exception as exc:  # pragma: no cover - بستهٔ ناقص
        _log(f"[T4] updater unavailable ({exc})")
        return False
    pending = None
    try:
        pending = updater.pending()
    except Exception as exc:  # pragma: no cover
        _log(f"[T4] pending update unreadable ({exc})")
        return False
    if not pending:
        return False
    if not updater.is_newer(str(pending.get("version") or ""), updater.current_version()):
        # آپدیت کهنه (نسخهٔ فعلی دیگر تازه‌تر است) دور ریخته می‌شود.
        updater.reset()
        return False
    try:
        request = updater.request_apply()
        updater.run_apply_script(str(request["script"]))
    except Exception as exc:
        _log(f"[T4] could not apply the staged update ({exc})")
        return False
    _log(f"[T4] update {pending.get('version')} is being applied; restarting")
    return True


def _watch_apply_request(window_box: dict, server, stop: threading.Event) -> None:
    """منتظر «اعمال آپدیت» از رابط کاربری؛ بعد پنجره بسته و اسکریپت اجرا می‌شود."""
    from app import updater

    while not stop.is_set():
        time.sleep(1)
        try:
            request = updater.take_apply_request()
        except Exception:  # pragma: no cover - فایل نیمه‌نوشته
            request = None
        if not request:
            continue
        _apply_state["script"] = request.get("script")
        _log("[T4] update requested; shutting down to replace files")
        stop.set()
        server.should_exit = True
        window = window_box.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:  # pragma: no cover - پنجرهٔ بسته‌شده
                pass
        return


_apply_state: dict = {"script": None}


def main():
    base = _base()
    os.environ["T4_DESKTOP"] = "1"
    os.environ["T4_WEB_DIR"] = str(base / "web")
    if "T4_DATA_DIR" not in os.environ:
        os.environ["T4_DATA_DIR"] = str(
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "T4Translate"
        )

    # آپدیتِ دانلودشده همان اول اعمال می‌شود؛ خودِ اسکریپت برنامه را دوباره باز می‌کند.
    if "--smoke-test" not in sys.argv and _apply_ready_update_on_start():
        return

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
            from app import updater
            _log(f"[T4] version: {updater.current_version()}")
        except Exception:  # pragma: no cover - بستهٔ ناقص
            pass

        stop = threading.Event()
        window_box: dict = {}
        watcher = threading.Thread(target=_watch_apply_request,
                                   args=(window_box, server, stop), daemon=True)
        watcher.start()
        try:
            import webview
        except Exception as exc:
            _log(f"[T4] window support unavailable ({exc}); using the browser")
            _browser_fallback(url, stop)
            return
        try:
            window_box["window"] = webview.create_window(
                "T-4 Translate", url, width=1200, height=820, min_size=(720, 560))
            webview.start()
        except Exception as exc:
            _log(f"[T4] window failed ({exc}); using the browser")
            _browser_fallback(url, stop)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        script = _apply_state.get("script")
        if script:
            # فایل‌های در حال اجرا الان آزاد شده‌اند؛ اسکریپت جابه‌جایی را انجام می‌دهد.
            try:
                from app import updater
                updater.run_apply_script(str(script))
                _log("[T4] applying update; the app will start again")
            except Exception as exc:  # pragma: no cover
                _log(f"[T4] update script failed ({exc})")
        sock.close()


if __name__ == "__main__":
    main()
