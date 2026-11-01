from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.request_limits import RequestBodyLimit


def make_app():
    app = FastAPI()
    app.add_middleware(RequestBodyLimit, max_bytes=10)

    @app.post('/')
    async def read(request: Request):
        return {'body': (await request.body()).decode()}
    return app


def test_body_within_limit_reaches_app():
    with TestClient(make_app()) as client:
        assert client.post('/', content=b'123').json() == {'body': '123'}


def test_over_limit_rejected_before_route():
    with TestClient(make_app()) as client:
        assert client.post('/', content=b'12345678901').status_code == 413


def test_over_limit_without_content_length():
    with TestClient(make_app()) as client:
        assert client.post('/', content=iter([b'123456', b'78901'])).status_code == 413
