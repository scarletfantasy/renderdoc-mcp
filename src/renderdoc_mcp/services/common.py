from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.errors import CapturePathError, ReplayFailureError, RenderDocMCPError
from renderdoc_mcp.paths import ui_config_path
from renderdoc_mcp.uri import encode_capture_path

NULL_LIKE_VALUES = {"", "null", "none", "undefined"}


class ServiceContext:
    def __init__(self, bridge: QRenderDocBridge | None = None) -> None:
        self.bridge = bridge or QRenderDocBridge()

    def capture_tool(self, normalized_path: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.bridge.ensure_capture_loaded(normalized_path)
        return self.bridge.call(method, params or {})

    def run_tool(self, capture_path: str, headline: str, callback: Any) -> dict[str, Any]:
        try:
            normalized = self.normalize_capture_path(capture_path)
            result = callback(normalized)
            return self.success_response(normalized, result, headline)
        except RenderDocMCPError as exc:
            return self.error_response(capture_path, exc, headline)
        except Exception as exc:  # pragma: no cover
            return self.error_response(
                capture_path,
                ReplayFailureError(
                    "Unexpected server error while talking to RenderDoc.",
                    {"exception_type": type(exc).__name__, "message": str(exc)},
                ),
                headline,
            )

    def success_response(self, capture_path: str, result: dict[str, Any], headline: str) -> dict[str, Any]:
        warnings: list[str] = []
        if result.get("truncated"):
            returned_count = result.get("returned_count")
            limit = result.get("limit")
            warnings.append(
                "Result was truncated to {} action nodes{}.".format(
                    limit,
                    " (returned {})".format(returned_count) if returned_count is not None else "",
                )
            )

        return {
            "capture": {"path": capture_path, "encoded_path": encode_capture_path(capture_path)},
            "result": result,
            "summary": {"headline": headline},
            "warnings": warnings,
            "error": None,
        }

    def error_response(self, capture_path: str, error: RenderDocMCPError, headline: str) -> dict[str, Any]:
        normalized = str(Path(capture_path)) if capture_path else ""
        return {
            "capture": {
                "path": normalized,
                "encoded_path": encode_capture_path(normalized) if normalized else "",
            },
            "result": None,
            "summary": {"headline": headline},
            "warnings": [],
            "error": error.to_payload(),
        }

    def normalize_capture_path(self, capture_path: str) -> str:
        path = Path(capture_path).expanduser()
        if not path.is_file():
            raise CapturePathError(str(path))
        return str(path.resolve())

    def read_ui_config(self) -> dict[str, Any]:
        path = ui_config_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

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
