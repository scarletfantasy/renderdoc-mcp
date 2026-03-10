from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from renderdoc_mcp.errors import CapturePathError, InvalidCaptureIDError, ReplayFailureError
from renderdoc_mcp.paths import ui_config_path
from renderdoc_mcp.session_pool import CaptureSession, CaptureSessionPool, get_capture_session_pool
from renderdoc_mcp.uri import normalize_capture_id

NULL_LIKE_VALUES = {"", "null", "none", "undefined"}
TRUE_LIKE_VALUES = {"1", "true", "yes", "on"}
FALSE_LIKE_VALUES = {"0", "false", "no", "off"}


class ApplicationContext:
    def __init__(self, session_pool: CaptureSessionPool | None = None) -> None:
        self._session_pool = session_pool or get_capture_session_pool()

    def open_capture(self, capture_path: str) -> CaptureSession:
        normalized_path = self.normalize_capture_path(capture_path)
        return self._session_pool.open(normalized_path)

    def close_capture(self, capture_id: str) -> bool:
        normalized_id = self.normalize_required_capture_id(capture_id)
        return self._session_pool.close(normalized_id)

    def get_session(self, capture_id: str) -> CaptureSession:
        normalized_id = self.normalize_required_capture_id(capture_id)
        session = self._session_pool.get(normalized_id)
        if session is None:
            raise InvalidCaptureIDError(normalized_id)
        return session

    def capture_tool(
        self,
        capture_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[CaptureSession, dict[str, Any]]:
        normalized_id = self.normalize_required_capture_id(capture_id)
        try:
            with self._session_pool.lease(normalized_id) as session:
                session.bridge.ensure_capture_loaded(session.capture_path)
                return session, session.bridge.call(method, params or {})
        except KeyError as exc:
            raise InvalidCaptureIDError(normalized_id) from exc

    def read_ui_config(self) -> dict[str, Any]:
        path = ui_config_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def normalize_capture_path(self, capture_path: str) -> str:
        path = Path(capture_path).expanduser()
        if not path.is_file():
            raise CapturePathError(str(path))
        return str(path.resolve())

    def normalize_required_capture_id(self, capture_id: Any) -> str:
        try:
            return normalize_capture_id(self.normalize_required_string(capture_id, "capture_id"))
        except ValueError as exc:
            raise ReplayFailureError(str(exc), {"capture_id": capture_id}) from exc

    def normalize_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value).strip()

        if normalized.lower() in NULL_LIKE_VALUES:
            return None

        return normalized

    def normalize_optional_int(self, value: Any, field_name: str) -> int | None:
        if value is None:
            return None

        if isinstance(value, str) and value.strip().lower() in NULL_LIKE_VALUES:
            return None

        return self.normalize_required_int(value, field_name)

    def normalize_optional_bool(self, value: Any, field_name: str) -> bool | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, int) and value in (0, 1):
            return bool(value)

        if isinstance(value, str):
            stripped = value.strip().lower()
            if stripped in NULL_LIKE_VALUES:
                return None
            if stripped in TRUE_LIKE_VALUES:
                return True
            if stripped in FALSE_LIKE_VALUES:
                return False
            raise ReplayFailureError(f"{field_name} must be a boolean.", {field_name: value})

        raise ReplayFailureError(f"{field_name} must be a boolean.", {field_name: value})

    def normalize_optional_float(self, value: Any, field_name: str) -> float | None:
        if value is None:
            return None

        if isinstance(value, bool):
            raise ReplayFailureError(f"{field_name} must be a number.", {field_name: value})

        if isinstance(value, (int, float)):
            normalized = float(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped.lower() in NULL_LIKE_VALUES:
                return None
            try:
                normalized = float(stripped)
            except ValueError as exc:
                raise ReplayFailureError(f"{field_name} must be a number.", {field_name: value}) from exc
        else:
            raise ReplayFailureError(f"{field_name} must be a number.", {field_name: value})

        if not math.isfinite(normalized):
            raise ReplayFailureError(f"{field_name} must be a finite number.", {field_name: value})

        return normalized

    def normalize_non_negative_float(self, value: Any, field_name: str) -> float:
        normalized = self.normalize_optional_float(value, field_name)
        assert normalized is not None
        if normalized < 0:
            raise ReplayFailureError(f"{field_name} must be greater than or equal to 0.", {field_name: normalized})
        return normalized

    def normalize_required_string(self, value: Any, field_name: str) -> str:
        normalized = self.normalize_optional_string(value)
        if normalized is None:
            raise ReplayFailureError(f"{field_name} must be a non-empty string.", {field_name: value})
        return normalized

    def normalize_required_int(self, value: Any, field_name: str) -> int:
        if isinstance(value, bool):
            raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value})

        if isinstance(value, int):
            return value

        if isinstance(value, float) and value.is_integer():
            return int(value)

        if isinstance(value, str):
            stripped = value.strip()
            try:
                return int(stripped)
            except ValueError as exc:
                raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value}) from exc

        raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value})

    def normalize_non_negative_int(self, value: Any, field_name: str) -> int:
        normalized = self.normalize_required_int(value, field_name)
        if normalized < 0:
            raise ReplayFailureError(f"{field_name} must be greater than or equal to 0.", {field_name: normalized})
        return normalized

    def normalize_positive_int(self, value: Any, field_name: str) -> int:
        normalized = self.normalize_required_int(value, field_name)
        if normalized <= 0:
            raise ReplayFailureError(f"{field_name} must be greater than 0.", {field_name: normalized})
        return normalized
