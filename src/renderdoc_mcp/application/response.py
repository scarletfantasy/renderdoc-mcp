from __future__ import annotations

from typing import Any

from renderdoc_mcp.backend import current_backend_name
from renderdoc_mcp.session_pool import CaptureSession


def runtime_meta() -> dict[str, Any]:
    return {"backend": current_backend_name()}


def bridge_meta(session: CaptureSession) -> dict[str, Any]:
    meta = runtime_meta()
    backend_name = getattr(session.bridge, "backend_name", None)
    if isinstance(backend_name, str) and backend_name:
        meta["backend"] = backend_name
    renderdoc_version = getattr(session.bridge, "renderdoc_version", None)
    if isinstance(renderdoc_version, str) and renderdoc_version:
        meta["renderdoc_version"] = renderdoc_version
    return meta


def _attach_bridge_meta(payload: dict[str, Any], session: CaptureSession) -> None:
    meta = payload.setdefault("meta", {})
    meta.update(bridge_meta(session))


def attach_capture(payload: dict[str, Any], session: CaptureSession) -> dict[str, Any]:
    payload["capture_id"] = session.capture_id
    payload["capture_path"] = session.capture_path
    _attach_bridge_meta(payload, session)
    return payload


def ensure_meta(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.setdefault("meta", {})
    meta.setdefault("backend", current_backend_name())
    return payload
