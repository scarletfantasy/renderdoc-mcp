from __future__ import annotations

import atexit
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol, TextIO

from renderdoc_mcp.backend import DEFAULT_BACKEND, NATIVE_PYTHON_BACKEND, current_backend_name
from renderdoc_mcp.errors import (
    BridgeDisconnectedError,
    BridgeHandshakeTimeoutError,
    CapturePathError,
    InvalidEventIDError,
    ReplayFailureError,
    RenderDocMCPError,
)
from renderdoc_mcp.paths import resolve_qrenderdoc_path
from renderdoc_mcp.protocol import BRIDGE_PROTOCOL_VERSION, close_socket, read_message, send_message


class RenderDocBridge(Protocol):
    backend_name: str
    renderdoc_version: str | None

    def ensure_capture_loaded(self, capture_path: str) -> dict[str, Any]:
        ...

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class QRenderDocBridge:
    """Owns the qrenderdoc process handshake and request/response socket."""

    backend_name = DEFAULT_BACKEND

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or _env_float("RENDERDOC_BRIDGE_TIMEOUT_SECONDS", 30.0)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._server_socket: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._reader: TextIO | None = None
        self._writer: TextIO | None = None
        self._current_capture: str | None = None
        self._current_capture_token: tuple[int, int] | None = None
        self._log_path: str | None = None
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
            close_socket(self._connection)
            self._connection = None
            close_socket(self._server_socket)
            self._server_socket = None
            self._log_path = None

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
        capture_token = (int(stat_result.st_size), int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))))
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
        if self._reader is not None and self._writer is not None and self._connection is not None:
            return

        qrenderdoc_path = resolve_qrenderdoc_path()
        last_log_path: str | None = None

        for attempt in range(2):
            self.close()

            listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_socket.bind(("127.0.0.1", 0))
            listen_socket.listen(1)
            listen_socket.settimeout(0.5)
            self._server_socket = listen_socket

            token = secrets.token_urlsafe(24)
            log_path = str(Path(tempfile.gettempdir()) / ("renderdoc_mcp_bridge_{}.log".format(token)))
            last_log_path = log_path
            self._log_path = log_path
            env = os.environ.copy()
            env.update(
                {
                    "RENDERDOC_MCP_BRIDGE_HOST": "127.0.0.1",
                    "RENDERDOC_MCP_BRIDGE_PORT": str(listen_socket.getsockname()[1]),
                    "RENDERDOC_MCP_BRIDGE_TOKEN": token,
                    "RENDERDOC_MCP_BRIDGE_PROTOCOL": str(BRIDGE_PROTOCOL_VERSION),
                    "RENDERDOC_MCP_BRIDGE_LOG": log_path,
                }
            )

            self._process = subprocess.Popen([str(qrenderdoc_path)], cwd=str(qrenderdoc_path.parent), env=env)

            deadline = time.monotonic() + self.timeout_seconds
            connection: socket.socket | None = None

            while time.monotonic() < deadline:
                try:
                    connection, _ = listen_socket.accept()
                    break
                except TimeoutError:
                    continue
                except OSError:
                    break

            if connection is None:
                self.close()
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise BridgeHandshakeTimeoutError(self.timeout_seconds, last_log_path)

            connection.settimeout(self.timeout_seconds)
            reader = connection.makefile("r", encoding="utf-8", newline="\n")
            writer = connection.makefile("w", encoding="utf-8", newline="\n")

            try:
                hello = read_message(reader)
                self._accept_hello(hello, token)
            except Exception as exc:
                writer.close()
                reader.close()
                close_socket(connection)
                self.close()
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                if isinstance(exc, ReplayFailureError):
                    raise
                raise BridgeHandshakeTimeoutError(self.timeout_seconds, last_log_path) from exc

            self._connection = connection
            self._reader = reader
            self._writer = writer
            close_socket(self._server_socket)
            self._server_socket = None
            return

        raise BridgeHandshakeTimeoutError(self.timeout_seconds, last_log_path)

    def _accept_hello(self, hello: dict[str, Any], token: str) -> None:
        if hello.get("type") != "hello" or hello.get("token") != token:
            self.renderdoc_version = None
            raise ReplayFailureError(
                "Received an invalid bridge handshake from qrenderdoc.",
                {"hello": hello, "log_path": self._log_path},
            )

        renderdoc_version = hello.get("renderdoc_version")
        if isinstance(renderdoc_version, str):
            normalized = renderdoc_version.strip()
            self.renderdoc_version = normalized or None
        else:
            self.renderdoc_version = None

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
            response = read_message(self._reader)
        except OSError as exc:
            self.close()
            raise BridgeDisconnectedError() from exc
        except ConnectionError as exc:
            self.close()
            raise BridgeDisconnectedError() from exc

        if response.get("type") != "response" or response.get("id") != request_id:
            raise ReplayFailureError("Received an invalid bridge response.", {"response": response})

        error = response.get("error")
        if error:
            self._raise_mapped_error(error)

        result = response.get("result")
        if not isinstance(result, dict):
            raise ReplayFailureError("Bridge response did not include a JSON object result.")
        return result

    def _raise_mapped_error(self, error: dict[str, Any]) -> None:
        code = error.get("code")
        message = error.get("message", "RenderDoc bridge request failed.")
        details = error.get("details")

        if code == "capture_path_not_found":
            raise CapturePathError(str((details or {}).get("capture_path", "")))
        if code == "invalid_event_id":
            raise InvalidEventIDError(int((details or {}).get("event_id", 0)))
        if code == "bridge_disconnected":
            self.close()
            raise BridgeDisconnectedError()
        raise RenderDocMCPError(str(code or "replay_failure"), message, details)


def create_default_bridge() -> RenderDocBridge:
    backend = current_backend_name()
    if backend == NATIVE_PYTHON_BACKEND:
        from renderdoc_mcp.native_bridge import NativePythonBridge

        return NativePythonBridge()

    return QRenderDocBridge()
