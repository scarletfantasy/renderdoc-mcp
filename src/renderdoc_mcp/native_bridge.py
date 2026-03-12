from __future__ import annotations

import atexit
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from typing import Any, TextIO

from renderdoc_mcp.backend import NATIVE_PYTHON_BACKEND, NativePythonConfig, resolve_native_python_config
from renderdoc_mcp.errors import (
    BridgeDisconnectedError,
    CapturePathError,
    InvalidEventIDError,
    NativeHelperStartupError,
    NativePythonImportError,
    NativePythonModuleNotFoundError,
    NativePythonNotConfiguredError,
    RenderDocMCPError,
)
from renderdoc_mcp.protocol import BRIDGE_PROTOCOL_VERSION, decode_message, send_message


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class NativePythonBridge:
    backend_name = NATIVE_PYTHON_BACKEND

    def __init__(
        self,
        config: NativePythonConfig | None = None,
        timeout_seconds: float | None = None,
        helper_module: str = "renderdoc_mcp.native_helper",
    ) -> None:
        self.timeout_seconds = timeout_seconds or _env_float("RENDERDOC_BRIDGE_TIMEOUT_SECONDS", 30.0)
        self._config = config
        self._helper_module = helper_module
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._reader: TextIO | None = None
        self._writer: TextIO | None = None
        self._message_queue: Queue[dict[str, Any] | None] = Queue()
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._current_capture: str | None = None
        self._current_capture_token: tuple[int, int] | None = None
        self.renderdoc_version: str | None = None
        atexit.register(self.close)

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._current_capture = None
            self._current_capture_token = None
            self.renderdoc_version = None
            if self._writer is not None:
                try:
                    self._writer.close()
                except OSError:
                    pass
                self._writer = None
            if self._reader is not None:
                try:
                    self._reader.close()
                except OSError:
                    pass
                self._reader = None

            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5.0)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            try:
                                process.wait(timeout=1.0)
                            except subprocess.TimeoutExpired:
                                pass
                except OSError:
                    pass

    def ensure_capture_loaded(self, capture_path: str) -> dict[str, Any]:
        path = Path(capture_path)
        normalized = str(path)
        stat_result = path.stat()
        capture_token = (
            int(stat_result.st_size),
            int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        )
        with self._lock:
            self.ensure_started()
            if self._current_capture == normalized and self._current_capture_token == capture_token:
                return {"loaded": True, "filename": normalized}
            result = self._call_locked("load_capture", {"capture_path": normalized})
            self._current_capture = normalized
            self._current_capture_token = capture_token
            return result

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.ensure_started()
            return self._call_locked(method, params or {})

    def ensure_started(self) -> None:
        if self._reader is not None and self._writer is not None and self._process is not None:
            if self._process.poll() is None:
                return
            self.close()

        config = self._config or resolve_native_python_config()
        env = os.environ.copy()
        src_root = Path(__file__).resolve().parents[1]
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else str(src_root) + os.pathsep + existing_pythonpath

        try:
            process = subprocess.Popen(
                [
                    config.python_executable,
                    "-m",
                    self._helper_module,
                    "--module-dir",
                    str(config.module_dir),
                    "--dll-dir",
                    str(config.dll_dir),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise NativeHelperStartupError(
                "Failed to launch the native RenderDoc helper process.",
                {"exception_type": type(exc).__name__, "exception": str(exc)},
            ) from exc
        self._process = process
        self._reader = process.stdout
        self._writer = process.stdin
        if self._reader is None or self._writer is None:
            self.close()
            raise NativeHelperStartupError("The native RenderDoc helper did not expose stdio pipes.")
        self._message_queue = Queue()
        self._stderr_lines.clear()

        self._stdout_thread = threading.Thread(target=self._stdout_reader_loop, name="renderdoc_native_stdout", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_reader_loop, name="renderdoc_native_stderr", daemon=True)
        self._stderr_thread.start()

        hello = self._wait_for_message()
        if hello is None:
            self.close()
            raise NativeHelperStartupError(
                "The native RenderDoc helper exited before completing its startup handshake.",
                self._startup_details(),
            )

        if hello.get("type") == "fatal":
            self.close()
            self._raise_mapped_error(hello.get("error", {}))

        if hello.get("type") != "hello":
            self.close()
            raise NativeHelperStartupError(
                "The native RenderDoc helper returned an invalid startup handshake.",
                {"message": hello, **self._startup_details()},
            )
        if hello.get("protocol_version") not in (None, BRIDGE_PROTOCOL_VERSION):
            self.close()
            raise NativeHelperStartupError(
                "The native RenderDoc helper reported an unsupported protocol version.",
                {"message": hello, **self._startup_details()},
            )

        renderdoc_version = hello.get("renderdoc_version")
        if renderdoc_version is None:
            self.renderdoc_version = None
        else:
            self.renderdoc_version = str(renderdoc_version).strip() or None

    def _stdout_reader_loop(self) -> None:
        reader = self._reader
        if reader is None:
            self._message_queue.put(None)
            return

        try:
            while True:
                line = reader.readline()
                if not line:
                    break
                self._message_queue.put(decode_message(line))
        except Exception as exc:
            self._message_queue.put(
                {
                    "type": "fatal",
                    "error": {
                        "code": "native_helper_startup_failed",
                        "message": "The native RenderDoc helper emitted invalid protocol data.",
                        "details": {"exception_type": type(exc).__name__, "exception": str(exc)},
                    },
                }
            )
        finally:
            self._message_queue.put(None)

    def _stderr_reader_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return

        try:
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                self._stderr_lines.append(line.rstrip())
        except Exception:
            return

    def _wait_for_message(self) -> dict[str, Any] | None:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeHelperStartupError(
                    "Timed out waiting for the native RenderDoc helper to respond.",
                    self._startup_details(),
                )
            try:
                message = self._message_queue.get(timeout=remaining)
            except Empty as exc:
                raise NativeHelperStartupError(
                    "Timed out waiting for the native RenderDoc helper to respond.",
                    self._startup_details(),
                ) from exc

            if message is None:
                return None
            return message

    def _call_locked(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._reader is None or self._writer is None:
            raise BridgeDisconnectedError()

        request_id = uuid.uuid4().hex
        try:
            send_message(
                self._writer,
                {
                    "type": "request",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
            )
        except OSError as exc:
            self.close()
            raise BridgeDisconnectedError() from exc

        response = self._wait_for_message()
        if response is None:
            self.close()
            raise BridgeDisconnectedError()

        if response.get("type") == "fatal":
            self.close()
            self._raise_mapped_error(response.get("error", {}))

        if response.get("type") != "response" or response.get("id") != request_id:
            raise RenderDocMCPError("replay_failure", "Received an invalid bridge response.", {"response": response})

        error = response.get("error")
        if error:
            self._raise_mapped_error(error)

        result = response.get("result")
        if not isinstance(result, dict):
            raise RenderDocMCPError("replay_failure", "Bridge response did not include a JSON object result.")
        return result

    def _startup_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if self._stderr_lines:
            details["stderr"] = "\n".join(self._stderr_lines)
        process = self._process
        if process is not None and process.poll() is not None:
            details["returncode"] = process.returncode
        return details

    def _raise_mapped_error(self, error: dict[str, Any]) -> None:
        code = error.get("code")
        message = error.get("message", "RenderDoc bridge request failed.")
        details = error.get("details") or {}

        if code == "capture_path_not_found":
            raise CapturePathError(str(details.get("capture_path", "")))
        if code == "invalid_event_id":
            raise InvalidEventIDError(int(details.get("event_id", 0)))
        if code == "native_python_not_configured":
            raise NativePythonNotConfiguredError(str(details.get("missing_env_var", "RENDERDOC_NATIVE_MODULE_DIR")))
        if code == "native_python_module_not_found":
            raise NativePythonModuleNotFoundError(
                str(details.get("checked_path", "")),
                kind=str(details.get("kind", "renderdoc_module")),
            )
        if code == "native_python_import_failed":
            raise NativePythonImportError(message, details)
        if code == "native_helper_startup_failed":
            raise NativeHelperStartupError(message, details)
        if code == "bridge_disconnected":
            self.close()
            raise BridgeDisconnectedError()
        raise RenderDocMCPError(str(code or "replay_failure"), message, details)
