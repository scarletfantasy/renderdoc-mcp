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


class RenderDocNotInstalledError(RenderDocMCPError):
    def __init__(self, checked_path: str | None = None) -> None:
        details = {"checked_path": checked_path} if checked_path else None
        super().__init__(
            "renderdoc_not_installed",
            "qrenderdoc.exe could not be found. Install RenderDoc or set RENDERDOC_QRENDERDOC_PATH.",
            details,
        )


class CapturePathError(RenderDocMCPError):
    def __init__(self, capture_path: str) -> None:
        super().__init__(
            "capture_path_not_found",
            "The supplied capture_path does not exist or is not a file.",
            {"capture_path": capture_path},
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
