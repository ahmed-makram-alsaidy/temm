"""Main FastAPI Application Entrypoint for TEMM (legacy package: ai_fleet)."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Set

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .storage.database import AsyncSessionLocal, engine, init_db
from .services.runs import run_lifecycle_service
from .api.routes import (
    fleet_router,
    health_router,
    models_router,
    agents_router,
    scanner_router,
    router_router,
    task_router,
    runs_router,
    benchmarks_router,
    arena_router,
    skills_router,
    workflows_router,
    secrets_router,
    chat_router,
    terminal_router,
    settings_router,
    budgets_router,
    analytics_router,
    workspace_router,
    projects_router,
    assets_router,
    asset_library_router,
    orchestrations_router,
    search_router,
    plugins_router,
    approvals_router,
    audit_router,
    providers_router,
)
from .engine.event_bus import task_event_bus
from .engine.process_manager import process_manager
from .errors import DomainError
from .security import SensitiveDataRedactor
from .storage.secret_vault import secret_vault


class WebSocketConnectionManager:
    """Manages active WebSockets for fleet event streaming and live terminals."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.terminal_channels: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast_event(self, event_type: str, data: dict):
        """Broadcast real-time fleet events to all connected clients."""
        payload = json.dumps({"type": event_type, "data": data, "timestamp": asyncio.get_event_loop().time()})
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                disconnected.add(connection)
        for d in disconnected:
            self.active_connections.discard(d)

    async def connect_terminal(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.terminal_channels:
            self.terminal_channels[task_id] = set()
        self.terminal_channels[task_id].add(websocket)

    def disconnect_terminal(self, task_id: str, websocket: WebSocket):
        if task_id in self.terminal_channels:
            self.terminal_channels[task_id].discard(websocket)
            if not self.terminal_channels[task_id]:
                del self.terminal_channels[task_id]

    async def stream_to_terminal(self, task_id: str, line: str, stream_type: str = "stdout"):
        if task_id in self.terminal_channels:
            payload = json.dumps({"stream": stream_type, "content": line})
            disconnected = set()
            for ws in self.terminal_channels[task_id]:
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.add(ws)
            for d in disconnected:
                self.terminal_channels[task_id].discard(d)


ws_manager = WebSocketConnectionManager()
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = 64 * 1024


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_HTTP_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = next((value for key, value in scope.get("headers", []) if key.lower() == b"content-length"), None)
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return
        received = 0
        rejected = False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message):
            if not rejected:
                await send(message)

        await self.app(scope, limited_receive, limited_send)
        if rejected:
            await self._reject(send)

    async def _reject(self, send):
        body = json.dumps({"detail": {"code": "request_too_large", "message": "Request body exceeds 2 MiB."}}).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


LOCAL_ORIGINS = [
    "http://localhost:8787",
    "http://127.0.0.1:8787",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def is_local_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


async def require_local_websocket_origin(websocket: WebSocket) -> bool:
    if is_local_origin(websocket.headers.get("origin")):
        return True
    await websocket.close(code=1008, reason="Origin is not allowed.")
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and seed initial data
    await init_db()
    async with AsyncSessionLocal() as session:
        await run_lifecycle_service.recover_interrupted(session)
    print("=" * 60)
    print("  TEMM — The Completion Runtime")
    print("  Local Command Center URL: http://localhost:8787")
    print("=" * 60)
    try:
        yield
    finally:
        try:
            await process_manager.shutdown()
        finally:
            await engine.dispose()


app = FastAPI(
    title="TEMM — The Completion Runtime",
    description="Operating system and command center for all AI models, CLIs, local LLMs, and delegate skills.",
    version="1.0.0",
    lifespan=lifespan,
)

def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if supplied and len(supplied) <= 128 and supplied.isascii() else f"req-{uuid.uuid4().hex}"


def _error_payload(request: Request, status_code: int, detail) -> dict:
    redactor = SensitiveDataRedactor.from_environment(secret_vault.redaction_values())
    if isinstance(detail, dict) and "code" in detail:
        code = detail.get("code", "request_failed")
        message = detail.get("message", "Request failed.")
        canonical = detail if "schema_version" in detail else {
            "schema_version": "1.0",
            "code": code,
            "category": "validation" if status_code == 422 else "request",
            "message": message,
            "retryable": False,
            "details": {key: value for key, value in detail.items() if key not in {"code", "message"}},
        }
    else:
        canonical = {
            "schema_version": "1.0",
            "code": "request_failed",
            "category": "validation" if status_code == 422 else "request",
            "message": detail if isinstance(detail, str) else "Request failed.",
            "retryable": False,
            "details": {},
        }
    return redactor.redact({
        "detail": detail,
        "error": canonical,
        "meta": {"request_id": getattr(request.state, "request_id", None), "timestamp": datetime.now(timezone.utc).isoformat()},
    })


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=_error_payload(request, exc.status_code, exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = [{"location": list(item["loc"]), "type": item["type"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content=_error_payload(request, 422, {"code": "validation_failed", "message": "The request is invalid.", "fields": details}))


@app.middleware("http")
async def response_metadata(request: Request, call_next):
    request.state.request_id = _request_id(request)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Response-Timestamp"] = datetime.now(timezone.utc).isoformat()
    response.headers["X-API-Schema-Version"] = "1.0"
    return response


@app.middleware("http")
async def local_browser_request_guard(request, call_next):
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    if host not in {"localhost", "127.0.0.1", "::1", "testserver", "test"}:
        return JSONResponse(status_code=400, content={"detail": {"code": "invalid_host", "message": "Host is not allowed."}})
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if origin and not is_local_origin(origin):
        return JSONResponse(status_code=403, content={"detail": {"code": "foreign_origin", "message": "Browser origin is not allowed."}})
    if fetch_site == "cross-site":
        return JSONResponse(status_code=403, content={"detail": {"code": "cross_site_request", "message": "Cross-site browser requests are not allowed."}})
    return await call_next(request)


app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_HTTP_BODY_BYTES)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver", "test"])

# Enable CORS for local development and Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
)

# Mount Routers
app.include_router(health_router)
app.include_router(fleet_router)
app.include_router(models_router)
app.include_router(agents_router)
app.include_router(scanner_router)
app.include_router(router_router)
app.include_router(task_router)
app.include_router(runs_router)
app.include_router(benchmarks_router)
app.include_router(arena_router)
app.include_router(skills_router)
app.include_router(workflows_router)
app.include_router(secrets_router)
app.include_router(chat_router)
app.include_router(terminal_router)
app.include_router(settings_router)
app.include_router(budgets_router)
app.include_router(analytics_router)
app.include_router(workspace_router)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(asset_library_router)
app.include_router(orchestrations_router)
app.include_router(search_router)
app.include_router(plugins_router)
app.include_router(approvals_router)
app.include_router(audit_router)
app.include_router(providers_router)


# Global WebSocket for Fleet events
@app.websocket("/ws/fleet")
async def websocket_fleet_endpoint(websocket: WebSocket):
    if not await require_local_websocket_origin(websocket):
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep alive and receive client events
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Task Terminal WebSocket for real-time streaming
async def close_terminal_stream(sender: asyncio.Task, receiver: asyncio.Task, release) -> None:
    """Stop a terminal socket's reader and writer, then release its subscription.

    Awaited with `asyncio.wait` and never with `gather`: gather re-raises whatever
    a child raised, and CPython propagates a cancelled child regardless of
    `return_exceptions`. So when this teardown is itself cancelled - a client that
    disconnects a moment before its handler finishes closing - gather substitutes
    the bare cancellation of the child for the caller's own. The caller's cancel
    scope does not recognise that substitute, refuses to absorb it, and reports an
    ordinary disconnect as a handler that crashed.

    `release` runs on every path, including a cancelled one: an interrupted
    teardown that never unsubscribes leaves the queue on the bus, and every later
    event for the task is published into a reader that will never drain it.
    """
    sender.cancel()
    receiver.cancel()
    try:
        await asyncio.wait({sender, receiver})
    finally:
        release()


@app.websocket("/ws/terminal/{task_id}")
async def websocket_terminal_endpoint(websocket: WebSocket, task_id: str):
    if not await require_local_websocket_origin(websocket):
        return
    await websocket.accept()
    try:
        after_sequence = max(0, int(websocket.query_params.get("after", "0")))
    except ValueError:
        after_sequence = 0
    queue = await task_event_bus.subscribe_persistent(task_id, after_sequence)
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock:
            await websocket.send_json(payload)

    async def send_events():
        await send({
            "type": "connected",
            "task_id": task_id,
            "status": process_manager.get_status(task_id),
            "pty": process_manager.pty_capability(),
        })
        while True:
            event = await queue.get()
            await send(event)

    async def receive_commands():
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                await send({"type": "command_error", "task_id": task_id, "message": "WebSocket message exceeds 64 KiB."})
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await send({"type": "command_error", "task_id": task_id, "message": "Malformed terminal command."})
                continue
            if not isinstance(message, dict):
                await send({"type": "command_error", "task_id": task_id, "message": "Terminal command must be an object."})
                continue
            command = message.get("type")
            try:
                if command == "stdin":
                    data = str(message.get("data", ""))
                    if len(data.encode("utf-8")) > 65536:
                        await send({"type": "command_error", "task_id": task_id, "message": "Terminal input exceeds 64 KiB."})
                        continue
                    accepted = await process_manager.write_stdin(task_id, data)
                elif command == "resize":
                    accepted = await process_manager.resize(task_id, int(message.get("columns", 0)), int(message.get("rows", 0)))
                elif command == "cancel":
                    accepted = await process_manager.cancel(task_id)
                    if accepted:
                        await task_event_bus.publish(task_id, "cancellation_requested", message="Cancellation requested from terminal.")
                elif command == "ping":
                    await send({"type": "pong", "task_id": task_id})
                    continue
                else:
                    await send({"type": "command_error", "task_id": task_id, "message": "Unsupported terminal command."})
                    continue
                if not accepted:
                    await send({"type": "command_error", "task_id": task_id, "message": "The interactive execution is not running."})
            except (TypeError, ValueError, RuntimeError) as exc:
                await send({"type": "command_error", "task_id": task_id, "message": str(exc)})

    def retrieve_outcome(finished: asyncio.Task) -> None:
        # Reading the outcome marks it handled. A socket that merely closed must
        # not be reported later as an unhandled task exception.
        if not finished.cancelled():
            finished.exception()

    sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_commands())
    sender.add_done_callback(retrieve_outcome)
    receiver.add_done_callback(retrieve_outcome)
    try:
        await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        await close_terminal_stream(sender, receiver, lambda: task_event_bus.unsubscribe(task_id, queue))


# Serve Vite Frontend static build if present
DIST_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "web" / "dist"

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path == "health" or full_path.startswith(("api/", "health/", "ws/")):
            raise HTTPException(status_code=404, detail={"code": "route_not_found", "message": "Backend route was not found."})
        file_path = DIST_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(DIST_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {
            "name": "TEMM API",
            "version": "1.0.0",
            "status": "online",
            "docs": "/docs",
            "frontend": "Frontend dev server running on Vite port or build required.",
        }
