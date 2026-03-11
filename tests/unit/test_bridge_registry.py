from __future__ import annotations

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
