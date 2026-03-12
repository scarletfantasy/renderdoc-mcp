from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RenderDocMCPError(RuntimeError):
    """Base class for errors surfaced as structured MCP results."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class RenderDocNotInstalledError(RenderDocMCPError):
    def __init__(self, checked_path: str | None = None) -> None:
        details = {"checked_path": checked_path} if checked_path else None
        super().__init__(
            "renderdoc_not_installed",
            "qrenderdoc.exe could not be found. Install RenderDoc or set RENDERDOC_QRENDERDOC_PATH.",
            details,
        )


class InvalidBackendError(RenderDocMCPError):
    def __init__(self, backend: str, supported_backends: list[str]) -> None:
        super().__init__(
            "invalid_backend",
            "RENDERDOC_BACKEND must be one of {}.".format(", ".join(supported_backends)),
            {"backend": backend, "supported_backends": supported_backends},
        )


class NativePythonNotConfiguredError(RenderDocMCPError):
    def __init__(self, missing_env_var: str) -> None:
        super().__init__(
            "native_python_not_configured",
            "The native RenderDoc Python backend is not configured.",
            {"missing_env_var": missing_env_var},
        )


class NativePythonModuleNotFoundError(RenderDocMCPError):
    def __init__(self, checked_path: str, kind: str = "renderdoc_module") -> None:
        super().__init__(
            "native_python_module_not_found",
            "The native RenderDoc Python backend files could not be found.",
            {"checked_path": checked_path, "kind": kind},
        )


class NativePythonImportError(RenderDocMCPError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("native_python_import_failed", message, details)


class NativeHelperStartupError(RenderDocMCPError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("native_helper_startup_failed", message, details)


class CapturePathError(RenderDocMCPError):
    def __init__(self, capture_path: str) -> None:
        super().__init__(
            "capture_path_not_found",
            "The supplied capture_path does not exist or is not a file.",
            {"capture_path": capture_path},
        )


class InvalidCaptureIDError(RenderDocMCPError):
    def __init__(self, capture_id: str) -> None:
        super().__init__(
            "invalid_capture_id",
            "The supplied capture_id does not exist or has already been closed.",
            {"capture_id": capture_id},
        )


class BridgeHandshakeTimeoutError(RenderDocMCPError):
    def __init__(self, timeout_seconds: float, log_path: str | None = None) -> None:
        details: dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if log_path:
            details["log_path"] = log_path
        super().__init__(
            "bridge_handshake_timeout",
            "Timed out waiting for qrenderdoc to connect back to the MCP bridge.",
            details,
        )


class BridgeDisconnectedError(RenderDocMCPError):
    def __init__(self) -> None:
        super().__init__(
            "bridge_disconnected",
            "The qrenderdoc bridge connection was lost. Restart the request to relaunch qrenderdoc.",
        )


class InvalidEventIDError(RenderDocMCPError):
    def __init__(self, event_id: int) -> None:
        super().__init__(
            "invalid_event_id",
            "The supplied event_id does not exist in the active capture.",
            {"event_id": event_id},
        )


class ReplayFailureError(RenderDocMCPError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("replay_failure", message, details)
