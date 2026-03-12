from __future__ import annotations

import sys
from pathlib import Path

import pytest

from renderdoc_mcp.backend import current_backend_name, resolve_native_python_config
from renderdoc_mcp.errors import InvalidBackendError, NativePythonModuleNotFoundError, NativePythonNotConfiguredError


def test_current_backend_defaults_to_qrenderdoc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDERDOC_BACKEND", raising=False)

    assert current_backend_name() == "qrenderdoc"


def test_current_backend_accepts_native_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDERDOC_BACKEND", "native_python")

    assert current_backend_name() == "native_python"


def test_current_backend_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDERDOC_BACKEND", "bogus")

    with pytest.raises(InvalidBackendError):
        current_backend_name()


def test_native_python_config_requires_module_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDERDOC_NATIVE_MODULE_DIR", raising=False)

    with pytest.raises(NativePythonNotConfiguredError):
        resolve_native_python_config()


def test_native_python_config_requires_renderdoc_module_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_dir = tmp_path / "renderdoc"
    module_dir.mkdir()
    monkeypatch.setenv("RENDERDOC_NATIVE_MODULE_DIR", str(module_dir))
    monkeypatch.setenv("RENDERDOC_NATIVE_PYTHON_EXE", sys.executable)

    with pytest.raises(NativePythonModuleNotFoundError) as exc_info:
        resolve_native_python_config()

    assert exc_info.value.details["kind"] == "renderdoc_module"


def test_native_python_config_uses_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_dir = tmp_path / "renderdoc"
    module_dir.mkdir()
    (module_dir / "renderdoc.pyd").write_bytes(b"")
    monkeypatch.setenv("RENDERDOC_NATIVE_MODULE_DIR", str(module_dir))
    monkeypatch.delenv("RENDERDOC_NATIVE_DLL_DIR", raising=False)
    monkeypatch.delenv("RENDERDOC_NATIVE_PYTHON_EXE", raising=False)

    config = resolve_native_python_config()

    assert config.module_dir == module_dir
    assert config.dll_dir == module_dir
    assert config.python_executable == sys.executable
