from __future__ import annotations

import atexit
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterator

from renderdoc_mcp.bridge import RenderDocBridge, create_default_bridge
from renderdoc_mcp.uri import create_capture_id


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(slots=True)
class CaptureSession:
    capture_id: str
    capture_path: str
    bridge: RenderDocBridge
    last_used_monotonic: float
    in_use_count: int = 0


class CaptureSessionPool:
    def __init__(
        self,
        idle_timeout_seconds: float | None = None,
        bridge_factory: Callable[[], RenderDocBridge] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.idle_timeout_seconds = (
            idle_timeout_seconds
            if idle_timeout_seconds is not None
            else _env_float("RENDERDOC_CAPTURE_SESSION_IDLE_SECONDS", 300.0)
        )
        self._bridge_factory = bridge_factory or create_default_bridge
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._sessions: dict[str, CaptureSession] = {}
        atexit.register(self.close_all)

    def open(self, capture_path: str) -> CaptureSession:
        now = self._monotonic()
        with self._lock:
            expired = self._pop_expired_locked(now)
            session = CaptureSession(
                capture_id=create_capture_id(),
                capture_path=capture_path,
                bridge=self._bridge_factory(),
                last_used_monotonic=now,
            )
            self._sessions[session.capture_id] = session
        self._close_sessions(expired)
        return session

    @contextmanager
    def lease(self, capture_id: str) -> Iterator[CaptureSession]:
        session = self._acquire(capture_id)
        try:
            yield session
        finally:
            self.release(capture_id)

    def get(self, capture_id: str) -> CaptureSession | None:
        with self._lock:
            return self._sessions.get(capture_id)

    def release(self, capture_id: str) -> None:
        now = self._monotonic()
        with self._lock:
            session = self._sessions.get(capture_id)
            if session is not None:
                if session.in_use_count > 0:
                    session.in_use_count -= 1
                session.last_used_monotonic = now
            expired = self._pop_expired_locked(now)
        self._close_sessions(expired)

    def close(self, capture_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(capture_id, None)
        self._close_sessions([session] if session is not None else [])
        return session is not None

    def evict_idle_sessions(self) -> list[str]:
        with self._lock:
            expired = self._pop_expired_locked(self._monotonic())
        self._close_sessions(expired)
        return [session.capture_id for session in expired]

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        self._close_sessions(sessions)

    def _acquire(self, capture_id: str) -> CaptureSession:
        now = self._monotonic()
        with self._lock:
            expired = self._pop_expired_locked(now)
            session = self._sessions.get(capture_id)
            if session is None:
                raise KeyError(capture_id)
            session.in_use_count += 1
            session.last_used_monotonic = now
        self._close_sessions(expired)
        return session

    def _pop_expired_locked(self, now: float) -> list[CaptureSession]:
        if self.idle_timeout_seconds <= 0:
            return []

        expired_ids = [
            capture_id
            for capture_id, session in self._sessions.items()
            if session.in_use_count == 0 and (now - session.last_used_monotonic) > self.idle_timeout_seconds
        ]
        return [self._sessions.pop(capture_id) for capture_id in expired_ids]

    def _close_sessions(self, sessions: list[CaptureSession]) -> None:
        for session in sessions:
            try:
                session.bridge.close()
            except Exception:
                pass


@lru_cache(maxsize=1)
def get_capture_session_pool() -> CaptureSessionPool:
    return CaptureSessionPool()
