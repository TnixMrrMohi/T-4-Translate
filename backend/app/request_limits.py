"""Limit request bodies before Starlette parses multipart uploads."""
from tempfile import SpooledTemporaryFile

from starlette.responses import PlainTextResponse


class RequestBodyLimit:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH'}:
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        try:
            size = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await PlainTextResponse('Invalid Content-Length', status_code=400)(scope, receive, send)
        if size < 0:
            return await PlainTextResponse('Invalid Content-Length', status_code=400)(scope, receive, send)
        if size > self.max_bytes:
            return await PlainTextResponse('Request too large', status_code=413)(scope, receive, send)
        with SpooledTemporaryFile(max_size=1024 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                total += len(chunk)
                if total > self.max_bytes:
                    return await PlainTextResponse('Request too large', status_code=413)(scope, receive, send)
                body.write(chunk)
                if not message.get('more_body', False):
                    break
            body.seek(0)
            finished = False

            async def replay():
                nonlocal finished
                if finished:
                    return await receive()
                chunk = body.read(1024 * 1024)
                finished = body.tell() >= total
                return {'type': 'http.request', 'body': chunk, 'more_body': not finished}

            await self.app(scope, replay, send)
