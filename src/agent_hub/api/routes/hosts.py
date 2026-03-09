"""Host proxy routes — connect/disconnect remote backends and proxy HTTP traffic.

WebSocket proxying is registered separately in ``app.py`` because FastAPI has
known issues resolving WebSocket routes under ``APIRouter`` path prefixes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from agent_hub.services.proxy_service import HostConfig, ProxyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hosts", tags=["hosts"])

# Headers that must not be forwarded (hop-by-hop)
_HOP_BY_HOP = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",  # aiohttp sets this from the body
    }
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ConnectRequest(BaseModel):
    id: str
    label: str
    kind: Literal["direct", "ssh"]
    base_url: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""
    ssh_key: str = ""
    remote_port: int = 18080


class ConnectResponse(BaseModel):
    host_id: str
    connected: bool = True


class DisconnectResponse(BaseModel):
    host_id: str
    disconnected: bool = True


class ConnectedHostsResponse(BaseModel):
    host_ids: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_proxy(request: Request) -> ProxyService:
    try:
        svc = request.app.state.provider.proxy_service
    except AttributeError:
        raise HTTPException(status_code=503, detail="ProxyService not available")
    return svc  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Connect / disconnect endpoints
# ---------------------------------------------------------------------------


@router.post("/connect", response_model=ConnectResponse)
async def connect_host(body: ConnectRequest, request: Request) -> ConnectResponse:
    """Connect to a remote backend (direct or SSH) and store the session."""
    proxy = _get_proxy(request)
    config = HostConfig(
        id=body.id,
        label=body.label,
        kind=body.kind,
        base_url=body.base_url,
        ssh_host=body.ssh_host,
        ssh_port=body.ssh_port,
        ssh_user=body.ssh_user,
        ssh_password=body.ssh_password,
        ssh_key=body.ssh_key,
        remote_port=body.remote_port,
    )
    try:
        await proxy.connect(config)
    except Exception as exc:
        logger.exception("Failed to connect host %r", body.id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ConnectResponse(host_id=body.id)


@router.post("/{host_id}/disconnect", response_model=DisconnectResponse)
async def disconnect_host(host_id: str, request: Request) -> DisconnectResponse:
    """Disconnect from a remote backend and release its session."""
    proxy = _get_proxy(request)
    await proxy.disconnect(host_id)
    return DisconnectResponse(host_id=host_id)


@router.get("/connected", response_model=ConnectedHostsResponse)
async def list_connected(request: Request) -> ConnectedHostsResponse:
    """Return host IDs that are currently connected."""
    proxy = _get_proxy(request)
    return ConnectedHostsResponse(host_ids=proxy.connected_ids())


# ---------------------------------------------------------------------------
# HTTP proxy
# ---------------------------------------------------------------------------


@router.api_route(
    "/{host_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def http_proxy(host_id: str, path: str, request: Request) -> Response:
    """Proxy an HTTP request to the remote backend for *host_id*."""
    import aiohttp

    proxy = _get_proxy(request)
    hs = proxy.get(host_id)
    if hs is None:
        raise HTTPException(status_code=404, detail=f"Host {host_id!r} not connected")

    url = f"{hs.base_url}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    body = await request.body()

    session: aiohttp.ClientSession = hs.http_session  # type: ignore[assignment]
    try:
        async with session.request(
            method=request.method,
            url=url,
            headers=forward_headers,
            data=body or None,
            allow_redirects=False,
        ) as resp:
            content = await resp.read()
            # Strip hop-by-hop from response headers too
            resp_headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in _HOP_BY_HOP
            }
            return Response(
                content=content,
                status_code=resp.status,
                headers=resp_headers,
            )
    except aiohttp.ClientError as exc:
        logger.warning("HTTP proxy error for host %r: %s", host_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# WebSocket proxy (function only — registered in app.py)
# ---------------------------------------------------------------------------


async def ws_proxy_endpoint(websocket: object, host_id: str) -> None:
    """Relay WebSocket frames between the client and a remote backend.

    This function is intentionally not decorated — it is registered directly
    on the ``FastAPI`` app in ``app.py`` to avoid path-prefix resolution issues
    with ``APIRouter`` and WebSocket routes.
    """
    import aiohttp
    from fastapi import WebSocket
    from fastapi.websockets import WebSocketDisconnect

    ws: WebSocket = websocket  # type: ignore[assignment]

    # Look up the host session
    proxy: ProxyService = _get_proxy(ws)  # type: ignore[arg-type]
    hs = proxy.get(host_id)
    if hs is None:
        await ws.close(code=4004, reason=f"Host {host_id!r} not connected")
        return

    await ws.accept()

    remote_ws_url = hs.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(remote_ws_url) as remote_ws:

            async def local_to_remote() -> None:
                try:
                    async for data in ws.iter_text():
                        if remote_ws.closed:
                            break
                        await remote_ws.send_str(data)
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.debug("local→remote relay error: %s", exc)

            async def remote_to_local() -> None:
                async for msg in remote_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await ws.send_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await ws.send_bytes(msg.data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break

            tasks = [
                asyncio.create_task(local_to_remote()),
                asyncio.create_task(remote_to_local()),
            ]
            _done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    except aiohttp.ClientError as exc:
        logger.warning("WS proxy connection error for host %r: %s", host_id, exc)
    except Exception as exc:
        logger.exception("WS proxy error for host %r", host_id)
        raise
    finally:
        await session.close()
        try:
            await ws.close()
        except Exception:
            pass
