from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from renderdoc_mcp.errors import (
    InvalidBackendError,
    NativePythonModuleNotFoundError,
    NativePythonNotConfiguredError,
)

DEFAULT_BACKEND = "qrenderdoc"
NATIVE_PYTHON_BACKEND = "native_python"
SUPPORTED_BACKENDS = [DEFAULT_BACKEND, NATIVE_PYTHON_BACKEND]


@dataclass(slots=True)
class NativePythonConfig:
    python_executable: str
    module_dir: Path
    dll_dir: Path

    @property
    def renderdoc_module_path(self) -> Path:
        return self.module_dir / "renderdoc.pyd"


def current_backend_name() -> str:
    raw = str(os.environ.get("RENDERDOC_BACKEND", DEFAULT_BACKEND) or DEFAULT_BACKEND).strip().lower()
    backend = raw or DEFAULT_BACKEND
    if backend not in SUPPORTED_BACKENDS:
        raise InvalidBackendError(backend, SUPPORTED_BACKENDS)
    return backend


def resolve_native_python_config() -> NativePythonConfig:
    module_dir_raw = str(os.environ.get("RENDERDOC_NATIVE_MODULE_DIR", "") or "").strip()
    if not module_dir_raw:
        raise NativePythonNotConfiguredError("RENDERDOC_NATIVE_MODULE_DIR")

    module_dir = Path(module_dir_raw)
    if not module_dir.is_dir():
        raise NativePythonModuleNotFoundError(str(module_dir), kind="module_dir")

    renderdoc_module_path = module_dir / "renderdoc.pyd"
    if not renderdoc_module_path.is_file():
        raise NativePythonModuleNotFoundError(str(renderdoc_module_path), kind="renderdoc_module")

    python_executable = str(os.environ.get("RENDERDOC_NATIVE_PYTHON_EXE", "") or "").strip() or sys.executable
    python_path = Path(python_executable)
    if not python_path.is_file():
        raise NativePythonModuleNotFoundError(str(python_path), kind="python_executable")

    dll_dir_raw = str(os.environ.get("RENDERDOC_NATIVE_DLL_DIR", "") or "").strip()
    dll_dir = Path(dll_dir_raw) if dll_dir_raw else module_dir
    if not dll_dir.is_dir():
        raise NativePythonModuleNotFoundError(str(dll_dir), kind="dll_dir")

    return NativePythonConfig(
        python_executable=str(python_path),
        module_dir=module_dir,
        dll_dir=dll_dir,
    )
