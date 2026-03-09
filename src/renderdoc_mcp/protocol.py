from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, TextIO

BRIDGE_PROTOCOL_VERSION = 1


@dataclass(slots=True)
class BridgeRequest:
    request_id: str
    method: str
    params: dict[str, Any]

    def to_message(self) -> dict[str, Any]:
        return {
            "type": "request",
            "id": self.request_id,
            "method": self.method,
            "params": self.params,
        }


@dataclass(slots=True)
class BridgeResponse:
    request_id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def encode_message(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(line: str) -> dict[str, Any]:
    return json.loads(line)


def send_message(stream: TextIO, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


def read_message(stream: TextIO) -> dict[str, Any]:
    line = stream.readline()
    if not line:
        raise ConnectionError("Bridge stream closed")
    return decode_message(line)


def close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass
