"""Local-only Host and Origin guard for the packaged desktop server."""
from urllib.parse import urlsplit
from starlette.responses import PlainTextResponse


class DesktopOriginGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        host = headers.get(b'host', b'').decode('latin-1').lower()
        server = scope.get('server')
        expected = f'127.0.0.1:{server[1]}' if server else ''
        if host != expected:
            return await PlainTextResponse('Invalid host', status_code=400)(scope, receive, send)
        if scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = headers.get(b'origin')
            fetch_site = headers.get(b'sec-fetch-site', b'').lower()
            if fetch_site == b'cross-site':
                return await PlainTextResponse('Cross-site request denied', status_code=403)(scope, receive, send)
            if origin:
                parsed = urlsplit(origin.decode('latin-1'))
                if parsed.scheme != 'http' or parsed.netloc.lower() != expected:
                    return await PlainTextResponse('Invalid origin', status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)
