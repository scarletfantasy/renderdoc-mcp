from __future__ import annotations

import importlib
import sys


def test_importing_server_has_no_runtime_side_effects(monkeypatch) -> None:
    called = []
    sys.modules.pop("renderdoc_mcp.server", None)
    monkeypatch.setattr("renderdoc_mcp.bootstrap.prepare_runtime", lambda: called.append("prepare_runtime"))

    server = importlib.import_module("renderdoc_mcp.server")

    assert called == []
    assert callable(server.create_mcp_app)
