"""Windows desktop host. A loopback server is shared only with this window."""
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path


def main():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    os.environ['T4_DESKTOP'] = '1'
    os.environ['T4_WEB_DIR'] = str(base / 'web')
    if 'T4_DATA_DIR' not in os.environ:
        os.environ['T4_DATA_DIR'] = str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'T4Translate')

    import uvicorn
    from app.main import app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('Local server failed to start')
            time.sleep(.1)
        if not server.started:
            raise RuntimeError('Local server startup timed out')
        if '--smoke-test' in sys.argv:
            with urllib.request.urlopen(url + '/healthz', timeout=5) as response:
                assert response.read() == b'ok'
            with urllib.request.urlopen(url + '/', timeout=5) as response:
                assert b'<div id="root">' in response.read()
            # Ensure native libraries and bundled OCR model files are loadable in the frozen app.
            from app.ocr import _engine
            _engine()
            from app.ocr import recognize
            from PIL import Image
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                image_path = Path(directory) / 'smoke.png'
                Image.new('RGB', (64, 64), 'white').save(image_path)
                recognize(image_path)
            return
        import webview
        webview.create_window('T-4 Translate', url, width=1200, height=820, min_size=(720, 560))
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


if __name__ == '__main__':
    main()
