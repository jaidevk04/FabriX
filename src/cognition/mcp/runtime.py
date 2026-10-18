"""Official MCP SDK transport hosting, isolated to loopback and a run token."""

import asyncio
import secrets
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server import MCPServer


class BearerGuard:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization", b"").decode()
            if not secrets.compare_digest(header, f"Bearer {self.token}"):
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


@dataclass(frozen=True)
class Endpoint:
    url: str
    token: str


@asynccontextmanager
async def serve(server: MCPServer):
    import uvicorn

    token = secrets.token_urlsafe(32)
    app = server.streamable_http_app(stateless_http=True)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    runtime = uvicorn.Server(
        uvicorn.Config(
            BearerGuard(app, token),
            host="127.0.0.1",
            log_level="error",
            access_log=False,
            timeout_graceful_shutdown=2,
        )
    )
    task = asyncio.create_task(runtime.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not runtime.started:
                if task.done():
                    await task
                    raise RuntimeError("Incident MCP server did not start")
                await asyncio.sleep(0.02)
        yield Endpoint(url=f"http://127.0.0.1:{port}/mcp", token=token)
    finally:
        runtime.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(task), 4)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        listener.close()
