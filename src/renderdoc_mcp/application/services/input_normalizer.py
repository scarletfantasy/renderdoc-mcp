from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from renderdoc_mcp.errors import CapturePathError, ReplayFailureError
from renderdoc_mcp.uri import normalize_capture_id

NULL_LIKE_VALUES = {"", "null", "none", "undefined"}
TRUE_LIKE_VALUES = {"1", "true", "yes", "on"}
FALSE_LIKE_VALUES = {"0", "false", "no", "off"}


class InputNormalizer:
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
