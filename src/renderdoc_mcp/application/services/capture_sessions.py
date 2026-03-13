from __future__ import annotations

from typing import Any

from renderdoc_mcp.application.services.input_normalizer import InputNormalizer
from renderdoc_mcp.errors import InvalidCaptureIDError
from renderdoc_mcp.session_pool import CaptureSession, CaptureSessionPool, get_capture_session_pool


class CaptureSessionService:
    def __init__(
        self,
        session_pool: CaptureSessionPool | None = None,
        normalizer: InputNormalizer | None = None,
    ) -> None:
        self._session_pool = session_pool or get_capture_session_pool()
        self._normalizer = normalizer or InputNormalizer()

    def open_capture(self, capture_path: str) -> CaptureSession:
        normalized_path = self._normalizer.normalize_capture_path(capture_path)
        return self.open_normalized_capture(normalized_path)

    def open_normalized_capture(self, capture_path: str) -> CaptureSession:
        return self._session_pool.open(capture_path)

    def close_capture(self, capture_id: str) -> bool:
        normalized_id = self._normalizer.normalize_required_capture_id(capture_id)
        return self.close_normalized_capture(normalized_id)

    def close_normalized_capture(self, capture_id: str) -> bool:
        return self._session_pool.close(capture_id)

    def get_session(self, capture_id: str) -> CaptureSession:
        normalized_id = self._normalizer.normalize_required_capture_id(capture_id)
        return self.get_normalized_session(normalized_id)

    def get_normalized_session(self, capture_id: str) -> CaptureSession:
        session = self._session_pool.get(capture_id)
        if session is None:
            raise InvalidCaptureIDError(capture_id)
        return session

    def capture_tool(
        self,
        capture_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[CaptureSession, dict[str, Any]]:
        normalized_id = self._normalizer.normalize_required_capture_id(capture_id)
        return self.capture_tool_normalized(normalized_id, method, params)

    def capture_tool_normalized(
        self,
        capture_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[CaptureSession, dict[str, Any]]:
        try:
            with self._session_pool.lease(capture_id) as session:
                session.bridge.ensure_capture_loaded(session.capture_path)
                return session, session.bridge.call(method, params or {})
        except KeyError as exc:
            raise InvalidCaptureIDError(capture_id) from exc
