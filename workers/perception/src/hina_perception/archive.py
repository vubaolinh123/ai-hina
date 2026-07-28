from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .errors import PerceptionError


_MAX_IN_MEMORY_SESSIONS = 8


@dataclass(slots=True)
class _SnapshotRecord:
    snapshot_id: str
    path: Path
    file_name: str
    byte_count: int
    captured_at: str

    def public(self, *, include_path: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "snapshotId": self.snapshot_id,
            "fileName": self.file_name,
            "bytes": self.byte_count,
            "capturedAt": self.captured_at,
            "historical": True,
            "decisionSupportEligible": False,
        }
        if include_path:
            payload["path"] = str(self.path)
        return payload


@dataclass(slots=True)
class _ArchiveSession:
    archive_session_id: str
    owner_session_id: str
    directory: Path
    started_at: str
    active: bool = True
    stopped_at: str | None = None
    byte_count: int = 0
    snapshots: dict[str, _SnapshotRecord] = field(default_factory=dict)

    def public(
        self,
        *,
        max_session_bytes: int,
        max_snapshots: int,
    ) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        return {
            "archiveSessionId": self.archive_session_id,
            "active": self.active,
            "path": str(self.directory),
            "startedAt": self.started_at,
            "stoppedAt": self.stopped_at,
            "snapshotCount": len(self.snapshots),
            "bytes": self.byte_count,
            "maxSessionBytes": max_session_bytes,
            "maxSnapshots": max_snapshots,
            "remainingBytes": max(0, max_session_bytes - self.byte_count),
            "remainingSnapshots": max(0, max_snapshots - len(self.snapshots)),
            "lastSnapshot": (
                latest.public(include_path=True)
                if latest is not None
                else None
            ),
            "manualCleanupRequired": True,
        }


class SessionSnapshotArchive:
    """Bounded owner-started PNG retention under a fixed physical root.

    The archive deliberately writes no metadata sidecar, OCR text, model output
    or prompt. Session and snapshot identifiers are service-generated UUIDs,
    so callers never provide a filesystem path. Stopping/closing only prevents
    future writes; the owner remains responsible for manually deleting PNGs
    after the game session, as explicitly requested for M08-S4.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_session_bytes: int,
        max_snapshots: int,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise PerceptionError(
                "E_PERCEPTION_CONFIG",
                "snapshot archive root must be an absolute Path",
            )
        self.root = root.resolve()
        self.max_session_bytes = max_session_bytes
        self.max_snapshots = max_snapshots
        self._sessions: dict[str, _ArchiveSession] = {}
        self._active_id: str | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            active = self._active_session()
            latest = next(reversed(self._sessions.values()), None) if self._sessions else None
            return {
                "available": not self._closed,
                "defaultEnabled": False,
                "active": active is not None,
                "root": str(self.root),
                "retainedSessionCountInRuntime": len(self._sessions),
                "current": (
                    active.public(
                        max_session_bytes=self.max_session_bytes,
                        max_snapshots=self.max_snapshots,
                    )
                    if active is not None
                    else None
                ),
                "latest": (
                    latest.public(
                        max_session_bytes=self.max_session_bytes,
                        max_snapshots=self.max_snapshots,
                    )
                    if latest is not None
                    else None
                ),
                "storesOnly": "validated image/png",
                "storesTextOrPrompts": False,
                "manualCleanupRequired": True,
            }

    async def start(self, *, owner_session_id: str) -> dict[str, Any]:
        _validate_uuid(owner_session_id, "owner session ID")
        async with self._lock:
            if self._closed:
                raise PerceptionError(
                    "E_PERCEPTION_UNAVAILABLE",
                    "snapshot archive is closed",
                    retryable=True,
                )
            active = self._active_session()
            if active is not None:
                if active.owner_session_id != owner_session_id:
                    raise PerceptionError(
                        "E_PERCEPTION_ARCHIVE_ACTIVE",
                        "another owner console session already owns the active archive",
                    )
                return {
                    "status": "already-active",
                    "archive": active.public(
                        max_session_bytes=self.max_session_bytes,
                        max_snapshots=self.max_snapshots,
                    ),
                }
            try:
                await asyncio.to_thread(self._ensure_root)
            except OSError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_WRITE",
                    "cannot prepare the snapshot archive root",
                    retryable=True,
                ) from exc
            archive_session_id = str(uuid4())
            directory = self._bounded_session_directory(archive_session_id)
            try:
                await asyncio.to_thread(directory.mkdir, parents=False, exist_ok=False)
            except FileExistsError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_WRITE",
                    "snapshot archive session already exists",
                ) from exc
            except OSError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_WRITE",
                    "cannot create the snapshot archive session",
                    retryable=True,
                ) from exc
            session = _ArchiveSession(
                archive_session_id=archive_session_id,
                owner_session_id=owner_session_id,
                directory=directory,
                started_at=_utc_now(),
            )
            self._sessions[archive_session_id] = session
            self._active_id = archive_session_id
            self._prune_session_index()
            return {
                "status": "started",
                "archive": session.public(
                    max_session_bytes=self.max_session_bytes,
                    max_snapshots=self.max_snapshots,
                ),
            }

    async def stop(
        self,
        *,
        owner_session_id: str,
        archive_session_id: str,
    ) -> dict[str, Any]:
        _validate_uuid(owner_session_id, "owner session ID")
        _validate_uuid(archive_session_id, "archive session ID")
        async with self._lock:
            session = self._owned_session(archive_session_id, owner_session_id)
            if session.active:
                session.active = False
                session.stopped_at = _utc_now()
                if self._active_id == archive_session_id:
                    self._active_id = None
                status = "stopped"
            else:
                status = "already-stopped"
            return {
                "status": status,
                "archive": session.public(
                    max_session_bytes=self.max_session_bytes,
                    max_snapshots=self.max_snapshots,
                ),
            }

    async def store(
        self,
        encoded_png: bytes,
        *,
        owner_session_id: str,
        archive_session_id: str,
    ) -> dict[str, Any]:
        _validate_uuid(owner_session_id, "owner session ID")
        _validate_uuid(archive_session_id, "archive session ID")
        if not isinstance(encoded_png, bytes) or not encoded_png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_WRITE",
                "snapshot archive accepts only validated PNG bytes",
            )
        async with self._lock:
            if self._closed:
                raise PerceptionError(
                    "E_PERCEPTION_UNAVAILABLE",
                    "snapshot archive is closed",
                    retryable=True,
                )
            session = self._owned_session(archive_session_id, owner_session_id)
            if not session.active or self._active_id != archive_session_id:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_STOPPED",
                    "snapshot archive session is not active",
                )
            if len(session.snapshots) >= self.max_snapshots:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_QUOTA",
                    "snapshot archive reached its image-count quota",
                )
            if session.byte_count + len(encoded_png) > self.max_session_bytes:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_QUOTA",
                    "snapshot archive reached its byte quota",
                )
            snapshot_id = str(uuid4())
            sequence = len(session.snapshots) + 1
            file_name = f"{sequence:06d}-{snapshot_id}.png"
            path = self._bounded_snapshot_path(session, file_name)
            try:
                await asyncio.to_thread(_write_exclusive, path, encoded_png)
            except FileExistsError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_WRITE",
                    "snapshot archive file already exists",
                ) from exc
            except OSError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_WRITE",
                    "cannot write the snapshot archive file",
                    retryable=True,
                ) from exc
            record = _SnapshotRecord(
                snapshot_id=snapshot_id,
                path=path,
                file_name=file_name,
                byte_count=len(encoded_png),
                captured_at=_utc_now(),
            )
            session.snapshots[snapshot_id] = record
            session.byte_count += len(encoded_png)
            return {
                "status": "archived",
                "archiveSessionId": archive_session_id,
                **record.public(include_path=True),
                "sessionSnapshotCount": len(session.snapshots),
                "sessionBytes": session.byte_count,
                "manualCleanupRequired": True,
            }

    async def read(
        self,
        *,
        owner_session_id: str,
        archive_session_id: str,
        snapshot_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        _validate_uuid(owner_session_id, "owner session ID")
        _validate_uuid(archive_session_id, "archive session ID")
        _validate_uuid(snapshot_id, "snapshot ID")
        async with self._lock:
            session = self._owned_session(archive_session_id, owner_session_id)
            record = session.snapshots.get(snapshot_id)
            if record is None:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_NOT_FOUND",
                    "snapshot is not available in this runtime archive index",
                )
            path = self._bounded_snapshot_path(session, record.file_name)
            try:
                encoded = await asyncio.to_thread(
                    _read_exact,
                    path,
                    record.byte_count,
                )
            except OSError as exc:
                raise PerceptionError(
                    "E_PERCEPTION_ARCHIVE_READ",
                    "cannot read the archived snapshot",
                    retryable=True,
                ) from exc
            return encoded, record.public(include_path=True)

    async def close(self) -> None:
        async with self._lock:
            active = self._active_session()
            if active is not None:
                active.active = False
                active.stopped_at = _utc_now()
            self._active_id = None
            self._closed = True

    def _active_session(self) -> _ArchiveSession | None:
        if self._active_id is None:
            return None
        session = self._sessions.get(self._active_id)
        return session if session is not None and session.active else None

    def _owned_session(
        self,
        archive_session_id: str,
        owner_session_id: str,
    ) -> _ArchiveSession:
        session = self._sessions.get(archive_session_id)
        if session is None:
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_NOT_FOUND",
                "snapshot archive session is not available in this runtime",
            )
        if session.owner_session_id != owner_session_id:
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_OWNER",
                "snapshot archive belongs to another owner console session",
            )
        return session

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise OSError("snapshot archive root is not a physical directory")

    def _bounded_session_directory(self, archive_session_id: str) -> Path:
        directory = (self.root / archive_session_id).resolve()
        if directory.parent != self.root:
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_PATH",
                "snapshot archive session escaped its fixed root",
            )
        return directory

    def _bounded_snapshot_path(
        self,
        session: _ArchiveSession,
        file_name: str,
    ) -> Path:
        if Path(file_name).name != file_name:
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_PATH",
                "snapshot archive file name is invalid",
            )
        resolved_directory = session.directory.resolve()
        if resolved_directory.parent != self.root or resolved_directory.is_symlink():
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_PATH",
                "snapshot archive session directory is no longer safe",
            )
        path = (resolved_directory / file_name).resolve()
        if path.parent != resolved_directory:
            raise PerceptionError(
                "E_PERCEPTION_ARCHIVE_PATH",
                "snapshot archive file escaped its session directory",
            )
        return path

    def _prune_session_index(self) -> None:
        if len(self._sessions) <= _MAX_IN_MEMORY_SESSIONS:
            return
        for session_id, session in tuple(self._sessions.items()):
            if len(self._sessions) <= _MAX_IN_MEMORY_SESSIONS:
                break
            if session_id != self._active_id and not session.active:
                self._sessions.pop(session_id, None)


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _read_exact(path: Path, expected_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OSError("snapshot archive file is unavailable")
    with path.open("rb") as stream:
        payload = stream.read(expected_bytes + 1)
    if len(payload) != expected_bytes:
        raise OSError("snapshot archive file size changed")
    return payload


def _validate_uuid(value: str, name: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} is invalid") from exc
    if str(parsed) != value.lower():
        raise PerceptionError("E_PERCEPTION_REQUEST", f"{name} must use canonical UUID form")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
