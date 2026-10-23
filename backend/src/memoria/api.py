"""REST routes and the interview/build WebSocket, as specified in docs/contract.md."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from memoria.models import (
    AssetRef,
    DocumentRef,
    EndInterview,
    ErrorEvent,
    InterviewComplete,
    RepUtterance,
    Session,
    SessionCreate,
    StartBuild,
    Tenant,
    TenantProfile,
)
from memoria.storage import NotFoundError, Storage, document_media_type

if TYPE_CHECKING:
    from memoria.app import Ports

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_TTS_CHARS = 600
# Same rule as SessionCreate.account_slug, so a document can only target slugs a session can use.
ACCOUNT_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"

RENDERED_MEDIA_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "html": "text/html",
    "eml": "message/rfc822",
}

_client_message = TypeAdapter(RepUtterance | EndInterview | StartBuild)


def _storage(request: Request) -> Storage:
    return request.app.state.storage


StorageDep = Annotated[Storage, Depends(_storage)]


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{exc} not found")


async def start_session(ports: Ports, storage: Storage, payload: SessionCreate) -> Session:
    """Create a session with the tenant's memory store ensured and its snapshot loaded."""
    tenant = storage.get_tenant(payload.tenant_id)
    if tenant.memory_store_id is None:
        tenant.memory_store_id = await ports.memory.ensure_store(tenant.id, tenant.profile.name)
        storage.save_tenant(tenant)
    session = storage.create_session(tenant.id, payload.account_slug, payload.rep_slug)
    session.memory_snapshot = await ports.memory.snapshot(tenant.memory_store_id, "/")
    storage.save_session(session)
    return session


# Health and tenants

@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": request.app.state.settings.mode}


@router.get("/tenants")
async def list_tenants(storage: StorageDep) -> list[Tenant]:
    return storage.list_tenants()


@router.post("/tenants", status_code=201)
async def create_tenant(profile: TenantProfile, storage: StorageDep) -> Tenant:
    return storage.create_tenant(profile)


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, storage: StorageDep) -> Tenant:
    try:
        return storage.get_tenant(tenant_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/tenants/{tenant_id}/documents", status_code=201)
async def upload_document(
    tenant_id: str,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    scope: Annotated[Literal["tenant", "account"], Form()],
    account_slug: Annotated[str | None, Form(pattern=ACCOUNT_SLUG_PATTERN)] = None,
) -> DocumentRef:
    try:
        storage.get_tenant(tenant_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    if scope == "account" and not account_slug:
        raise HTTPException(status_code=422, detail="account_slug is required when scope is account")
    media_type = document_media_type(file.filename or "")
    if media_type is None:
        raise HTTPException(status_code=415, detail="only PDF, DOCX, MD and TXT documents are accepted")
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="documents are limited to 20 MB")
    return storage.add_document(
        tenant_id, filename=file.filename or "", media_type=media_type, data=data, scope=scope,
        account_slug=account_slug if scope == "account" else None,
    )


# Sessions and files

@router.post("/sessions", status_code=201)
async def create_session(payload: SessionCreate, request: Request) -> Session:
    try:
        return await start_session(request.app.state.ports, request.app.state.storage, payload)
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, storage: StorageDep) -> Session:
    try:
        return storage.get_session(session_id)
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/sessions/{session_id}/assets")
async def get_assets(session_id: str, storage: StorageDep) -> list[AssetRef]:
    try:
        return storage.get_session(session_id).assets
    except NotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/files/{session_id}/{filename}")
async def get_file(session_id: str, filename: str, storage: StorageDep) -> FileResponse:
    try:
        path = storage.rendered_file(session_id, filename)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    media_type = RENDERED_MEDIA_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})


class TtsRequest(BaseModel):
    text: str
    voice: str | None = Field(default=None)


@router.post("/tts")
async def synthesize(payload: TtsRequest, request: Request) -> Response:
    if not payload.text.strip() or len(payload.text) > MAX_TTS_CHARS:
        raise HTTPException(status_code=400, detail=f"text must be 1 to {MAX_TTS_CHARS} characters")
    try:
        wav = await request.app.state.ports.tts.synthesize(payload.text, payload.voice)
    except Exception as exc:
        logger.exception("speech synthesis failed")
        raise HTTPException(status_code=502, detail="speech synthesis failed") from exc
    return Response(content=wav, media_type="audio/wav")


# WebSocket

class _Outbox:
    """Serializes sends on one socket and tolerates the client leaving mid-build."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._lock = asyncio.Lock()
        self.closed = False

    async def send(self, event: BaseModel) -> None:
        if self.closed:
            return
        async with self._lock:
            try:
                await self._websocket.send_text(event.model_dump_json())
            except (WebSocketDisconnect, RuntimeError):
                logger.info("client went away before a %s event could be delivered", type(event).__name__)
                self.closed = True


class _Connection:
    """One interview socket: forwards engine and build events and persists the session."""

    def __init__(self, websocket: WebSocket, session: Session, tenant: Tenant) -> None:
        self.state = websocket.app.state
        self.storage: Storage = self.state.storage
        self.websocket = websocket
        self.session = session
        self.tenant = tenant
        self.outbox = _Outbox(websocket)

    async def serve(self) -> None:
        if not self.session.turns:
            await self._turn(self.state.engine.opening(self.session, self.tenant))
        try:
            while True:
                raw = await self.websocket.receive_text()
                try:
                    message = _client_message.validate_json(raw)
                except ValidationError as exc:
                    await self.outbox.send(ErrorEvent(message=f"invalid message: {exc.errors()[0]['msg']}"))
                    continue
                await self._handle(message)
        except WebSocketDisconnect:
            logger.info("session %s socket closed", self.session.id)

    async def _handle(self, message: RepUtterance | EndInterview | StartBuild) -> None:
        if isinstance(message, StartBuild):
            await self._start_build()
        elif self.session.phase != "interview":
            await self.outbox.send(ErrorEvent(message="the interview is over; the build has started"))
        elif isinstance(message, EndInterview):
            await self.outbox.send(InterviewComplete(reason="rep_ended"))
        else:
            await self._turn(self.state.engine.handle_utterance(self.session, self.tenant, message.text))

    async def _turn(self, events: AsyncIterator[BaseModel]) -> None:
        try:
            async for event in events:
                await self.outbox.send(event)
        except Exception as exc:
            logger.exception("interview turn failed for session %s", self.session.id)
            await self.outbox.send(ErrorEvent(message=str(exc) or type(exc).__name__, recoverable=True))
        finally:
            self.storage.save_session(self.session)

    async def _start_build(self) -> None:
        # Reload: another socket for this session may already have started the build.
        current = self.storage.get_session(self.session.id)
        self.session = current
        if current.phase != "interview":
            await self.outbox.send(ErrorEvent(message="the build has already started for this session"))
            return
        current.phase = "building"
        self.storage.save_session(current)
        task = asyncio.create_task(self._forward_build(current))
        self.state.build_tasks.add(task)
        task.add_done_callback(self.state.build_tasks.discard)

    async def _forward_build(self, session: Session) -> None:
        try:
            async for event in self.state.runner.run(session, self.tenant):
                await self.outbox.send(event)
        except Exception as exc:
            logger.exception("build failed for session %s", session.id)
            await self.outbox.send(ErrorEvent(message=str(exc) or type(exc).__name__, recoverable=False))


@router.websocket("/sessions/{session_id}/ws")
async def interview_socket(websocket: WebSocket, session_id: str) -> None:
    state = websocket.app.state
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in state.settings.cors_origins:
        await websocket.close(code=1008)
        return
    try:
        session = state.storage.get_session(session_id)
        tenant = state.storage.get_tenant(session.tenant_id)
    except NotFoundError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await _Connection(websocket, session, tenant).serve()
