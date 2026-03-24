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

from agent_hub.services.proxy_service import HostConfig, HostSession, ProxyService
from agent_hub.services.remote_installer import InstallStatus, RemoteInstaller

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

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


class StoreCredentialRequest(BaseModel):
    auth_method: Literal["password", "key"]
    credential: str  # password or PEM key content


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
    auth_required: bool = False


class AuthenticateRequest(BaseModel):
    username: str
    password: str


class AuthenticateResponse(BaseModel):
    authenticated: bool


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


@router.post("/{host_id}/credential")
async def store_credential(
    host_id: str, body: StoreCredentialRequest, request: Request
) -> JSONResponse:
    """Store an SSH credential for a host in the backend credential store."""
    from fastapi.responses import JSONResponse

    cred_store = request.app.state.provider.credential_store
    key = f"host:{host_id}:ssh_{body.auth_method}"
    cred_store.store(key, body.credential)
    return JSONResponse({"stored": True})


@router.delete("/{host_id}/credential")
async def delete_credential(host_id: str, request: Request) -> JSONResponse:
    """Delete stored SSH credentials for a host."""
    from fastapi.responses import JSONResponse

    cred_store = request.app.state.provider.credential_store
    cred_store.delete(f"host:{host_id}:ssh_password")
    cred_store.delete(f"host:{host_id}:ssh_key")
    return JSONResponse({"deleted": True})


@router.post("/connect", response_model=ConnectResponse)
async def connect_host(body: ConnectRequest, request: Request) -> ConnectResponse:
    """Connect to a remote backend (direct or SSH) and store the session."""
    proxy = _get_proxy(request)

    # Retrieve SSH credentials from backend store if not provided in request
    ssh_password = body.ssh_password
    ssh_key = body.ssh_key
    if body.kind == "ssh" and not ssh_password and not ssh_key:
        cred_store = request.app.state.provider.credential_store
        ssh_password = cred_store.retrieve(f"host:{body.id}:ssh_password") or ""
        ssh_key = cred_store.retrieve(f"host:{body.id}:ssh_key") or ""

    config = HostConfig(
        id=body.id,
        label=body.label,
        kind=body.kind,
        base_url=body.base_url,
        ssh_host=body.ssh_host,
        ssh_port=body.ssh_port,
        ssh_user=body.ssh_user,
        ssh_password=ssh_password,
        ssh_key=ssh_key,
        remote_port=body.remote_port,
    )
    try:
        await proxy.connect(config)
    except Exception as exc:
        logger.exception("Failed to connect host %r", body.id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Check if the remote backend requires PAM authentication
    auth_required = False
    hs = proxy.get(body.id)
    if hs is not None:
        # Try to use a stored token first
        cred_store = request.app.state.provider.credential_store
        stored_token = cred_store.retrieve(f"host:{body.id}:remote_token")
        if stored_token:
            hs.remote_auth_token = stored_token

        auth_required = await _check_remote_auth(hs)

    return ConnectResponse(host_id=body.id, auth_required=auth_required)


async def _check_remote_auth(hs: HostSession) -> bool:
    """Probe the remote backend's auth status. Returns True if auth is needed."""
    import aiohttp

    session: aiohttp.ClientSession = hs.http_session  # type: ignore[assignment]
    cookies = {}
    if hs.remote_auth_token:
        cookies["agent_hub_token"] = hs.remote_auth_token
    try:
        async with session.get(
            f"{hs.base_url}/api/auth/status", cookies=cookies
        ) as resp:
            if resp.status != 200:
                return False  # Remote doesn't have auth routes — no auth needed
            data = await resp.json()
            return not data.get("authenticated", True)
    except Exception:
        return False  # Can't reach remote auth endpoint — assume no auth


@router.post("/{host_id}/authenticate", response_model=AuthenticateResponse)
async def authenticate_remote(
    host_id: str, body: AuthenticateRequest, request: Request
) -> AuthenticateResponse:
    """Authenticate with a remote host's PAM and store the resulting token."""
    import aiohttp

    proxy = _get_proxy(request)
    hs = proxy.get(host_id)
    if hs is None:
        raise HTTPException(status_code=404, detail=f"Host {host_id!r} not connected")

    session: aiohttp.ClientSession = hs.http_session  # type: ignore[assignment]
    try:
        async with session.post(
            f"{hs.base_url}/api/auth/login",
            json={"username": body.username, "password": body.password},
        ) as resp:
            if resp.status != 200:
                detail = "Remote authentication failed"
                try:
                    err_data = await resp.json()
                    detail = err_data.get("detail", detail)
                except Exception:
                    pass
                raise HTTPException(status_code=resp.status, detail=detail)

            # Extract the token from Set-Cookie header
            token: str | None = None
            for cookie in resp.cookies.values():
                if cookie.key == "agent_hub_token":
                    token = cookie.value
                    break

            if not token:
                raise HTTPException(
                    status_code=502, detail="Remote did not return auth token"
                )

            # Store token for this host session and persist it
            hs.remote_auth_token = token
            cred_store = request.app.state.provider.credential_store
            cred_store.store(f"host:{host_id}:remote_token", token)

            return AuthenticateResponse(authenticated=True)
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
# Remote install endpoints
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    """SSH connection details for install / status check.

    Sent in the POST body (not query params) to avoid leaking host info
    into server access logs.
    """

    ssh_host: str
    ssh_port: int = 22
    ssh_user: str = ""


class InstallStatusResponse(BaseModel):
    installed: bool
    running: bool
    version: str | None
    local_version: str
    update_available: bool


@router.post("/{host_id}/install")
async def install_remote(
    host_id: str, body: InstallRequest, request: Request
) -> StreamingResponse:
    """Install or update Agent Hub on a remote host via SSH.

    Streams install output as text/plain so the frontend can display progress
    in real time.
    """

    import uuid

    # Unique per-request sentinel — cannot collide with script output
    fail_sentinel = f"__INSTALL_FAILED_{uuid.uuid4().hex}__"

    async def generate() -> asyncio.AsyncGenerator[str, None]:
        async with _ssh_for_install(host_id, body, request) as ssh_conn:
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def on_output(text: str) -> None:
                await queue.put(text)

            async def _run_install() -> None:
                try:
                    success = await RemoteInstaller.install(ssh_conn, on_output)
                    if not success:
                        await queue.put(f"\n{fail_sentinel}\n")
                except Exception as exc:
                    await queue.put(f"ERROR: {exc}\n")
                finally:
                    await queue.put(None)  # sentinel — end of stream

            task = asyncio.create_task(_run_install())
            try:
                # Yield the sentinel to the frontend as the very first chunk
                # so it knows what to look for.
                yield f"__SENTINEL__:{fail_sentinel}\n"
                while True:
                    chunk = await queue.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                if not task.done():
                    task.cancel()
                    # Await so the task's finally block runs (closes resources)
                    await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(generate(), media_type="text/plain")


@router.get("/{host_id}/install-status", response_model=InstallStatusResponse)
async def install_status(host_id: str, request: Request) -> InstallStatusResponse:
    """Check whether Agent Hub is installed and running on a remote host.

    SSH params are passed as query params (acceptable for GET — no secrets).
    """
    params = request.query_params
    body = InstallRequest(
        ssh_host=params.get("ssh_host", ""),
        ssh_port=int(params.get("ssh_port", "22")),
        ssh_user=params.get("ssh_user", ""),
    )

    try:
        async with _ssh_for_install(host_id, body, request) as ssh_conn:
            status: InstallStatus = await RemoteInstaller.check_status(ssh_conn)
    except HTTPException:
        local_ver = RemoteInstaller.local_version()
        return InstallStatusResponse(
            installed=False,
            running=False,
            version=None,
            local_version=local_ver,
            update_available=False,
        )

    local_ver = RemoteInstaller.local_version()
    update_available = (
        status["installed"]
        and status["version"] is not None
        and status["version"] != local_ver
    )

    return InstallStatusResponse(
        installed=status["installed"],
        running=status["running"],
        version=status["version"],
        local_version=local_ver,
        update_available=update_available,
    )


@asynccontextmanager
async def _ssh_for_install(
    host_id: str, body: InstallRequest, request: Request
) -> AsyncIterator[object]:
    """Yield an SSH connection for install operations, closing it on exit.

    If the host is already connected via ProxyService, reuses that connection
    (and does *not* close it).  Otherwise opens a temporary one from stored
    credentials and closes it when the block exits.
    """
    import asyncssh  # type: ignore[import-untyped]

    proxy = _get_proxy(request)
    hs = proxy.get(host_id)

    if hs is not None and hs.ssh_conn is not None:
        # Reuse the existing session — do not close on exit
        yield hs.ssh_conn
        return

    # Open a temporary connection
    cred_store = request.app.state.provider.credential_store

    ssh_password = cred_store.retrieve(f"host:{host_id}:ssh_password") or ""
    ssh_key = cred_store.retrieve(f"host:{host_id}:ssh_key") or ""

    if not body.ssh_host:
        raise HTTPException(
            status_code=400,
            detail="ssh_host is required (in body or via active connection)",
        )

    connect_kwargs: dict[str, object] = {
        "host": body.ssh_host,
        "port": body.ssh_port,
        "username": body.ssh_user or None,
        # TODO: Support host key verification / pinning.  Currently uses
        # trust-on-first-use (same as ProxyService._create_ssh_session).
        "known_hosts": None,
    }
    if ssh_password:
        connect_kwargs["password"] = ssh_password
    if ssh_key:
        connect_kwargs["client_keys"] = [asyncssh.import_private_key(ssh_key)]

    try:
        conn = await asyncssh.connect(**connect_kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SSH connection failed: {exc}") from exc

    try:
        yield conn
    finally:
        conn.close()


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

    # Inject remote auth token as cookie if we have one
    if hs.remote_auth_token:
        existing_cookies = forward_headers.get("cookie", "")
        token_cookie = f"agent_hub_token={hs.remote_auth_token}"
        forward_headers["cookie"] = (
            f"{existing_cookies}; {token_cookie}" if existing_cookies else token_cookie
        )

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

    # Forward remote auth token as cookie on WS upgrade
    ws_cookies: dict[str, str] = {}
    if hs.remote_auth_token:
        ws_cookies["agent_hub_token"] = hs.remote_auth_token

    session = aiohttp.ClientSession(cookies=ws_cookies)
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
