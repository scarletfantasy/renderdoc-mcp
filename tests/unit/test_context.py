from __future__ import annotations

from pathlib import Path

from renderdoc_mcp.application.context import ApplicationContext
from renderdoc_mcp.session_pool import CaptureSessionPool


class DummyBridge:
    def close(self) -> None:
        return None


def _context() -> ApplicationContext:
    pool = CaptureSessionPool(bridge_factory=DummyBridge)
    return ApplicationContext(session_pool=pool)


def test_read_ui_config_returns_empty_dict_for_invalid_json(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "UI.config"
    config_path.write_text("{invalid", encoding="utf-8")
    context = _context()

    monkeypatch.setattr("renderdoc_mcp.application.context.ui_config_path", lambda: config_path)

    assert context.read_ui_config() == {}


def test_read_ui_config_returns_empty_dict_for_non_object_payload(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "UI.config"
    config_path.write_text('["not", "an", "object"]', encoding="utf-8")
    context = _context()

    monkeypatch.setattr("renderdoc_mcp.application.context.ui_config_path", lambda: config_path)

    assert context.read_ui_config() == {}
