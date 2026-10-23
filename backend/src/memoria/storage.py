"""File-backed persistence for tenants, sessions, uploaded documents and rendered files.

Layout under data_dir:
    tenants/<tenant_id>/tenant.json
    tenants/<tenant_id>/documents/<document_id>/<filename>
    sessions/<session_id>/session.json
    sessions/<session_id>/rendered/<filename>

Every JSON write goes through a temp file and os.replace, so a crash never leaves a
half-written record behind.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from memoria.models import DocumentRef, Session, Tenant, TenantProfile

DOCUMENT_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 120


class NotFoundError(LookupError):
    """The requested tenant, session, document or file does not exist."""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def sanitize_filename(name: str) -> str:
    """Reduce a client-supplied filename to a safe single path component."""
    base = re.split(r"[\\/]", name)[-1]
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).lstrip(".")
    suffix = Path(cleaned).suffix
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    cleaned = stem[: _MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return cleaned or "file"


def document_media_type(filename: str) -> str | None:
    """Media type for an uploadable document, or None when the type is not accepted."""
    return DOCUMENT_MEDIA_TYPES.get(Path(filename).suffix.lower())


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _write_model(path: Path, model: BaseModel) -> None:
    _write_atomic(path, model.model_dump_json(indent=2).encode("utf-8"))


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    # Tenants

    def _tenant_dir(self, tenant_id: str) -> Path:
        if not _ID_PATTERN.match(tenant_id):
            raise NotFoundError(f"tenant {tenant_id}")
        return self.data_dir / "tenants" / tenant_id

    def create_tenant(self, profile: TenantProfile) -> Tenant:
        tenant = Tenant(id=new_id(), profile=profile)
        self.save_tenant(tenant)
        return tenant

    def save_tenant(self, tenant: Tenant) -> None:
        _write_model(self._tenant_dir(tenant.id) / "tenant.json", tenant)

    def get_tenant(self, tenant_id: str) -> Tenant:
        path = self._tenant_dir(tenant_id) / "tenant.json"
        try:
            return Tenant.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            raise NotFoundError(f"tenant {tenant_id}") from None

    def list_tenants(self) -> list[Tenant]:
        root = self.data_dir / "tenants"
        if not root.is_dir():
            return []
        tenants = [self.get_tenant(p.name) for p in root.iterdir() if (p / "tenant.json").is_file()]
        return sorted(tenants, key=lambda t: (t.profile.name.lower(), t.id))

    # Dataset registry: lets the CLI reuse one tenant (and so its memory store) across rounds.

    def dataset_tenant_id(self, dataset_name: str) -> str | None:
        return self._read_dataset_registry().get(dataset_name)

    def remember_dataset_tenant(self, dataset_name: str, tenant_id: str) -> None:
        registry = self._read_dataset_registry()
        registry[dataset_name] = tenant_id
        _write_atomic(self.data_dir / "datasets.json", json.dumps(registry, indent=2).encode("utf-8"))

    def _read_dataset_registry(self) -> dict[str, str]:
        try:
            return json.loads((self.data_dir / "datasets.json").read_bytes())
        except FileNotFoundError:
            return {}

    # Documents

    def add_document(
        self,
        tenant_id: str,
        *,
        filename: str,
        media_type: str,
        data: bytes,
        scope: Literal["tenant", "account"],
        account_slug: str | None,
    ) -> DocumentRef:
        tenant = self.get_tenant(tenant_id)
        ref = DocumentRef(
            id=new_id(), filename=sanitize_filename(filename), media_type=media_type,
            size_bytes=len(data), scope=scope, account_slug=account_slug,
        )
        _write_atomic(self._document_path(tenant_id, ref), data)
        tenant.documents.append(ref)
        self.save_tenant(tenant)
        return ref

    def _document_path(self, tenant_id: str, ref: DocumentRef) -> Path:
        return self._tenant_dir(tenant_id) / "documents" / ref.id / ref.filename

    def read_document(self, tenant_id: str, ref: DocumentRef) -> bytes:
        try:
            return self._document_path(tenant_id, ref).read_bytes()
        except FileNotFoundError:
            raise NotFoundError(f"document {ref.id}") from None

    # Sessions

    def _session_dir(self, session_id: str) -> Path:
        if not _ID_PATTERN.match(session_id):
            raise NotFoundError(f"session {session_id}")
        return self.data_dir / "sessions" / session_id

    def create_session(self, tenant_id: str, account_slug: str, rep_slug: str) -> Session:
        session = Session(id=new_id(), tenant_id=tenant_id, account_slug=account_slug, rep_slug=rep_slug)
        self.save_session(session)
        return session

    def save_session(self, session: Session) -> None:
        _write_model(self._session_dir(session.id) / "session.json", session)

    def get_session(self, session_id: str) -> Session:
        path = self._session_dir(session_id) / "session.json"
        try:
            return Session.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            raise NotFoundError(f"session {session_id}") from None

    # Rendered files

    def rendered_dir(self, session_id: str) -> Path:
        path = self._session_dir(session_id) / "rendered"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def rendered_file(self, session_id: str, filename: str) -> Path:
        """Resolve a rendered file, refusing anything that is not directly inside the session's directory."""
        directory = self._session_dir(session_id) / "rendered"
        candidate = directory / filename
        if filename != sanitize_filename(filename) or not candidate.is_file():
            raise NotFoundError(f"file {filename}")
        if candidate.resolve().parent != directory.resolve():
            raise NotFoundError(f"file {filename}")
        return candidate
