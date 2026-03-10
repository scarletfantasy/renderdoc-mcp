from __future__ import annotations

from typing import Any

from renderdoc_mcp.session_pool import CaptureSession


def _attach_bridge_meta(payload: dict[str, Any], session: CaptureSession) -> None:
    meta = payload.setdefault("meta", {})
    renderdoc_version = getattr(session.bridge, "renderdoc_version", None)
    if isinstance(renderdoc_version, str) and renderdoc_version:
        meta.setdefault("renderdoc_version", renderdoc_version)


def attach_capture(payload: dict[str, Any], session: CaptureSession) -> dict[str, Any]:
    payload["capture_id"] = session.capture_id
    payload["capture_path"] = session.capture_path
    _attach_bridge_meta(payload, session)
    return payload


def ensure_meta(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("meta", {})
    return payload
