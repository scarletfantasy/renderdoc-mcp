import json
import os
import threading
import time
import traceback

from .component import BridgeComponent
from .transport import _WinSockClient, _log


class BridgeRuntime(BridgeComponent):
    def start(self):
        host = os.environ.get("RENDERDOC_MCP_BRIDGE_HOST")
        port = os.environ.get("RENDERDOC_MCP_BRIDGE_PORT")
        token = os.environ.get("RENDERDOC_MCP_BRIDGE_TOKEN")
        protocol = os.environ.get("RENDERDOC_MCP_BRIDGE_PROTOCOL")
        _log("Bridge start requested host={} port={} protocol={}".format(host, port, protocol))

        if not host or not port or not token:
            _log("Bridge env vars missing, not connecting.")
            return False

        if protocol and int(protocol) != self.PROTOCOL_VERSION:
            _log("Protocol mismatch: expected {}, got {}".format(self.PROTOCOL_VERSION, protocol))
            return False

        deadline = time.time() + self.CONNECT_RETRY_SECONDS

        while time.time() < deadline and not self.stop_event.is_set():
            try:
                sock = _WinSockClient()
                sock.connect(host, int(port))
                self.sock = sock
                self._send(
                    {
                        "type": "hello",
                        "token": token,
                        "protocol_version": self.PROTOCOL_VERSION,
                        "renderdoc_version": self.renderdoc_version or os.environ.get("RENDERDOC_VERSION", ""),
                    }
                )
                _log("Bridge connected and hello sent.")
                self.thread = threading.Thread(target=self._run, name="renderdoc_mcp_bridge", daemon=True)
                self.thread.start()
                return True
            except Exception:
                _log("Bridge connection attempt failed:\n{}".format(traceback.format_exc()))
                time.sleep(0.25)

        _log("Bridge failed to connect before timeout.")
        return False

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            if threading.current_thread() is not self.thread:
                self.thread.join(timeout=2.0)
            self.thread = None
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._clear_analysis_cache()

    def _send(self, message):
        self.sock.send_text(json.dumps(message, separators=(",", ":")) + "\n")

    def _read(self):
        return json.loads(self.sock.recv_line())

    def _invoke_on_ui_thread(self, callback):
        done = threading.Event()
        result = {}

        def runner():
            try:
                result["value"] = callback()
            except self.bridge_error_type as exc:
                result["error"] = exc.to_payload()
            except Exception:
                result["error"] = {
                    "code": "replay_failure",
                    "message": "RenderDoc request failed.",
                    "details": {"traceback": traceback.format_exc()},
                }
            finally:
                done.set()

        self.mqt.InvokeOntoUIThread(runner)
        done.wait()

        if "error" in result:
            raise self.bridge_error_type.from_payload(result["error"])

        return result.get("value", {})

    def _dispatch(self, method, params):
        handler = self.handlers.get(method)
        if handler is None:
            raise self.bridge_error_type("replay_failure", "Unknown bridge method.", {"method": method})
        return handler(params or {})

    def _run(self):
        while not self.stop_event.is_set():
            try:
                request = self._read()
            except TimeoutError:
                continue
            except Exception:
                _log("Bridge read failed, stopping loop:\n{}".format(traceback.format_exc()))
                break

            request_id = request.get("id")
            try:
                result = self._invoke_on_ui_thread(lambda: self._dispatch(request.get("method", ""), request.get("params", {})))
                response = {"type": "response", "id": request_id, "result": result}
            except Exception as exc:
                response = {"type": "response", "id": request_id, "error": self._parse_exception(exc)}

            try:
                self._send(response)
            except Exception:
                _log("Bridge write failed, stopping loop:\n{}".format(traceback.format_exc()))
                break

        self.stop()

    def _parse_exception(self, exc):
        if isinstance(exc, self.bridge_error_type):
            return exc.to_payload()
        try:
            payload = json.loads(str(exc))
            if isinstance(payload, dict) and "message" in payload:
                return payload
        except Exception:
            pass

        return {
            "code": "replay_failure",
            "message": str(exc),
            "details": {"traceback": traceback.format_exc()},
        }
