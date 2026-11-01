from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.desktop_security import DesktopOriginGuard


def test_desktop_rejects_untrusted_hosts_and_cross_origins():
    app = FastAPI()
    app.add_middleware(DesktopOriginGuard)
    @app.post('/')
    def action():
        return {'ok': True}
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        assert client.post('/', headers={'origin': 'http://127.0.0.1:8000'}).status_code == 200
        assert client.post('/', headers={'origin': 'https://evil.example'}).status_code == 403
        assert client.post('/', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
        assert client.post('/', headers={'host': 'evil.example'}).status_code == 400
