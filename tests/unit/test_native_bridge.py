from __future__ import annotations

import sys
from pathlib import Path

import pytest

from renderdoc_mcp.backend import NativePythonConfig
from renderdoc_mcp.errors import BridgeDisconnectedError, NativePythonImportError
from renderdoc_mcp.native_bridge import NativePythonBridge


def _config(tmp_path: Path) -> NativePythonConfig:
    module_dir = tmp_path / "renderdoc"
    module_dir.mkdir()
    (module_dir / "renderdoc.pyd").write_bytes(b"")
    return NativePythonConfig(
        python_executable=sys.executable,
        module_dir=module_dir,
        dll_dir=module_dir,
    )


def test_native_bridge_round_trips_requests_via_helper_process(tmp_path: Path) -> None:
    bridge = NativePythonBridge(
        config=_config(tmp_path),
        timeout_seconds=5.0,
        helper_module="tests.helpers.fake_native_helper",
    )
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    try:
        loaded = bridge.ensure_capture_loaded(str(capture_path))
        response = bridge.call("echo", {"value": 1})
    finally:
        bridge.close()

    assert bridge.backend_name == "native_python"
    assert bridge.renderdoc_version is None
    assert loaded == {"loaded": True, "filename": str(capture_path)}
    assert response == {"method": "echo", "params": {"value": 1}}


def test_native_bridge_maps_helper_startup_fatal_to_import_error(tmp_path: Path) -> None:
    bridge = NativePythonBridge(
        config=_config(tmp_path),
        timeout_seconds=5.0,
        helper_module="tests.helpers.failing_native_helper",
    )

    with pytest.raises(NativePythonImportError):
        bridge.ensure_started()


def test_native_bridge_reports_disconnect_when_helper_exits_after_hello(tmp_path: Path) -> None:
    bridge = NativePythonBridge(
        config=_config(tmp_path),
        timeout_seconds=5.0,
        helper_module="tests.helpers.exiting_native_helper",
    )

    with pytest.raises(BridgeDisconnectedError):
        bridge.call("echo", {"value": 1})

    bridge.close()
