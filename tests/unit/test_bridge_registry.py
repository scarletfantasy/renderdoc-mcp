from __future__ import annotations

from renderdoc_mcp.application.registry import TOOL_SPECS
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge.client import BridgeClient


class FakeMiniQt:
    def InvokeOntoUIThread(self, callback):
        callback()


class FakeExtensions:
    def GetMiniQtHelper(self):
        return FakeMiniQt()


class FakeContext:
    def Extensions(self):
        return FakeExtensions()


def test_bridge_client_registers_v2_handler_registry() -> None:
    client = BridgeClient(FakeContext())

    assert {
        "get_capture_overview",
        "get_analysis_worklist",
        "list_pipeline_bindings",
        "get_shader_code_chunk",
        "start_pixel_shader_debug",
        "continue_shader_debug",
        "get_shader_debug_step",
        "end_shader_debug",
        "close_capture",
    }.issubset(set(client.handlers))


def test_bridge_client_handlers_cover_registered_tool_bridge_methods() -> None:
    client = BridgeClient(FakeContext())

    bridge_methods = {spec.bridge_method for spec in TOOL_SPECS}

    assert bridge_methods.issubset(set(client.handlers))
