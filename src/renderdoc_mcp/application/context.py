from __future__ import annotations

from typing import Any

from renderdoc_mcp.application.services import CaptureSessionService, InputNormalizer, UIConfigRepository
from renderdoc_mcp.paths import ui_config_path
from renderdoc_mcp.session_pool import CaptureSession, CaptureSessionPool


class ApplicationContext:
    def __init__(
        self,
        session_pool: CaptureSessionPool | None = None,
        sessions: CaptureSessionService | None = None,
        normalizer: InputNormalizer | None = None,
        ui_config: UIConfigRepository | None = None,
    ) -> None:
        self.normalizer = normalizer or InputNormalizer()
        self.sessions = sessions or CaptureSessionService(session_pool=session_pool, normalizer=self.normalizer)
        self.ui_config = ui_config or UIConfigRepository()

    def open_capture(self, capture_path: str) -> CaptureSession:
        return self.sessions.open_capture(capture_path)

    def close_capture(self, capture_id: str) -> bool:
        return self.sessions.close_capture(capture_id)

    def get_session(self, capture_id: str) -> CaptureSession:
        return self.sessions.get_session(capture_id)

    def capture_tool(
        self,
        capture_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[CaptureSession, dict[str, Any]]:
        return self.sessions.capture_tool(capture_id, method, params)

    def read_ui_config(self) -> dict[str, Any]:
        return self.ui_config.read(ui_config_path())

    def normalize_capture_path(self, capture_path: str) -> str:
        return self.normalizer.normalize_capture_path(capture_path)

    def normalize_required_capture_id(self, capture_id: Any) -> str:
        return self.normalizer.normalize_required_capture_id(capture_id)

    def normalize_optional_string(self, value: Any) -> str | None:
        return self.normalizer.normalize_optional_string(value)

    def normalize_optional_int(self, value: Any, field_name: str) -> int | None:
        return self.normalizer.normalize_optional_int(value, field_name)

    def normalize_optional_bool(self, value: Any, field_name: str) -> bool | None:
        return self.normalizer.normalize_optional_bool(value, field_name)

    def normalize_optional_float(self, value: Any, field_name: str) -> float | None:
        return self.normalizer.normalize_optional_float(value, field_name)

    def normalize_non_negative_float(self, value: Any, field_name: str) -> float:
        return self.normalizer.normalize_non_negative_float(value, field_name)

    def normalize_required_string(self, value: Any, field_name: str) -> str:
        return self.normalizer.normalize_required_string(value, field_name)

    def normalize_required_int(self, value: Any, field_name: str) -> int:
        return self.normalizer.normalize_required_int(value, field_name)

    def normalize_non_negative_int(self, value: Any, field_name: str) -> int:
        return self.normalizer.normalize_non_negative_int(value, field_name)

    def normalize_positive_int(self, value: Any, field_name: str) -> int:
        return self.normalizer.normalize_positive_int(value, field_name)
