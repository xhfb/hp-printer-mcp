import contextlib
import sys
from collections.abc import AsyncIterator

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from hp_printer_mcp.server import mcp


def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    sse = SseServerTransport("/messages/")
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/mcp", app=handle_streamable_http),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    import argparse

    import uvicorn

    mcp_server = mcp._mcp_server

    parser = argparse.ArgumentParser(description="Run HP Smart Tank 750 MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run with Streamable HTTP and SSE transport instead of STDIO",
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Deprecated alias for --http",
    )
    parser.add_argument("--host", default=None, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument(
        "--port", type=int, default=None, help="Port to listen on (default: 3002)"
    )
    args = parser.parse_args()

    use_http = args.http or args.sse

    if not use_http and (args.host or args.port):
        parser.error("Host and port are only valid with --http")
        sys.exit(1)

    if use_http:
        host = args.host or "127.0.0.1"
        if host not in ("127.0.0.1", "localhost"):
            print(
                "\nWARNING: Binding to a non-localhost interface exposes printer "
                "control without authentication.\n",
                file=sys.stderr,
            )
        starlette_app = create_starlette_app(mcp_server, debug=True)
        uvicorn.run(starlette_app, host=host, port=args.port or 3002)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
