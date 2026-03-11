from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _find_capture() -> str | None:
    override = os.environ.get("RENDERDOC_MCP_CAPTURE")
    if override and Path(override).is_file():
        return str(Path(override).resolve())

    documents = Path.home() / "Documents"
    if documents.is_dir():
        for path in sorted(documents.glob("*.rdc")):
            return str(path.resolve())
    return None


def _size_bytes(payload: object) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


@pytest.mark.integration
def test_stdio_tools_and_resources() -> None:
    capture_path = _find_capture()
    if capture_path is None:
        pytest.skip("No local .rdc capture was found for integration testing.")

    async def run_test() -> None:
        env = os.environ.copy()
        env.setdefault("RENDERDOC_BRIDGE_TIMEOUT_SECONDS", "180")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "renderdoc_mcp"],
            env=env,
        )

        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                tool_names = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "renderdoc_open_capture",
                    "renderdoc_close_capture",
                    "renderdoc_get_capture_overview",
                    "renderdoc_get_analysis_worklist",
                    "renderdoc_list_passes",
                    "renderdoc_get_pass_summary",
                    "renderdoc_list_timing_events",
                    "renderdoc_list_actions",
                    "renderdoc_get_action_summary",
                    "renderdoc_get_pipeline_overview",
                    "renderdoc_list_pipeline_bindings",
                    "renderdoc_get_shader_summary",
                    "renderdoc_get_shader_code_chunk",
                    "renderdoc_list_resources",
                    "renderdoc_get_resource_summary",
                    "renderdoc_get_pixel_history",
                    "renderdoc_debug_pixel",
                    "renderdoc_start_pixel_shader_debug",
                    "renderdoc_continue_shader_debug",
                    "renderdoc_get_shader_debug_step",
                    "renderdoc_end_shader_debug",
                    "renderdoc_get_texture_data",
                    "renderdoc_get_buffer_data",
                    "renderdoc_save_texture_to_file",
                }.issubset(tool_names)

                opened = await session.call_tool("renderdoc_open_capture", {"capture_path": capture_path})
                assert not opened.isError
                opened_payload = opened.structuredContent
                assert opened_payload is not None
                capture_id = opened_payload["capture_id"]

                overview = await session.call_tool("renderdoc_get_capture_overview", {"capture_id": capture_id})
                assert not overview.isError
                overview_payload = overview.structuredContent
                assert overview_payload["capture_id"] == capture_id
                assert "capabilities" in overview_payload

                worklist = await session.call_tool(
                    "renderdoc_get_analysis_worklist",
                    {"capture_id": capture_id, "focus": "performance", "limit": 10},
                )
                assert not worklist.isError
                assert worklist.structuredContent["count"] <= 10

                root_passes = await session.call_tool(
                    "renderdoc_list_passes",
                    {"capture_id": capture_id, "cursor": 0, "limit": 50},
                )
                assert not root_passes.isError
                assert root_passes.structuredContent["meta"]["page"]["limit"] == 50
                assert _size_bytes(root_passes.structuredContent) < 25 * 1024
                root_pass_rows = root_passes.structuredContent["passes"]
                assert root_pass_rows is not None

                chosen_pass = root_pass_rows[0] if root_pass_rows else None
                child_pass_rows = []
                if chosen_pass is not None and chosen_pass["child_pass_count"] > 0:
                    child_passes = await session.call_tool(
                        "renderdoc_list_passes",
                        {"capture_id": capture_id, "parent_pass_id": chosen_pass["pass_id"], "limit": 50},
                    )
                    assert not child_passes.isError
                    child_pass_rows = child_passes.structuredContent["passes"]
                    if child_pass_rows:
                        chosen_pass = child_pass_rows[0]

                if chosen_pass is not None:
                    pass_summary = await session.call_tool(
                        "renderdoc_get_pass_summary",
                        {"capture_id": capture_id, "pass_id": chosen_pass["pass_id"]},
                    )
                    assert not pass_summary.isError
                    assert "child_passes" not in pass_summary.structuredContent
                    assert _size_bytes(pass_summary.structuredContent) < 10 * 1024

                    timing = await session.call_tool(
                        "renderdoc_list_timing_events",
                        {"capture_id": capture_id, "pass_id": chosen_pass["pass_id"], "limit": 100},
                    )
                    assert not timing.isError
                    assert timing.structuredContent["meta"]["page"]["limit"] == 100
                    assert _size_bytes(timing.structuredContent) < 30 * 1024

                root_actions = await session.call_tool(
                    "renderdoc_list_actions",
                    {"capture_id": capture_id, "cursor": 0, "limit": 50},
                )
                assert not root_actions.isError
                root_action_rows = root_actions.structuredContent["actions"]
                assert root_actions.structuredContent["meta"]["page"]["limit"] == 50

                chosen_event = None
                chosen_draw_event = None
                if root_action_rows:
                    first_action = root_action_rows[0]
                    if first_action["child_count"] > 0:
                        child_actions = await session.call_tool(
                            "renderdoc_list_actions",
                            {"capture_id": capture_id, "parent_event_id": first_action["event_id"], "limit": 50},
                        )
                        assert not child_actions.isError
                        for item in child_actions.structuredContent["actions"]:
                            if "draw" in item["flags"] and chosen_draw_event is None:
                                chosen_draw_event = item["event_id"]
                            if chosen_event is None and set(item["flags"]).intersection({"draw", "dispatch"}):
                                chosen_event = item["event_id"]
                            if chosen_event is not None and chosen_draw_event is not None:
                                break
                    if chosen_event is None:
                        probe_actions = await session.call_tool(
                            "renderdoc_list_actions",
                            {"capture_id": capture_id, "limit": 200, "flags_filter": "draw"},
                        )
                        assert not probe_actions.isError
                        for item in probe_actions.structuredContent["actions"]:
                            if "draw" in item["flags"] and chosen_draw_event is None:
                                chosen_draw_event = item["event_id"]
                            if chosen_event is None and ("draw" in item["flags"] or "dispatch" in item["flags"]):
                                chosen_event = item["event_id"]
                            if chosen_event is not None and chosen_draw_event is not None:
                                break
                if chosen_event is None and chosen_draw_event is not None:
                    chosen_event = chosen_draw_event

                if chosen_event is not None:
                    action_summary = await session.call_tool(
                        "renderdoc_get_action_summary",
                        {"capture_id": capture_id, "event_id": chosen_event},
                    )
                    assert not action_summary.isError
                    assert action_summary.structuredContent["action"]["event_id"] == chosen_event

                    pipeline = await session.call_tool(
                        "renderdoc_get_pipeline_overview",
                        {"capture_id": capture_id, "event_id": chosen_event},
                    )
                    assert not pipeline.isError
                    assert _size_bytes(pipeline.structuredContent) < 12 * 1024

                    descriptor_bindings = await session.call_tool(
                        "renderdoc_list_pipeline_bindings",
                        {
                            "capture_id": capture_id,
                            "event_id": chosen_event,
                            "binding_kind": "descriptor_accesses",
                            "limit": 50,
                        },
                    )
                    assert not descriptor_bindings.isError

                    shaders = pipeline.structuredContent["pipeline"]["shaders"]
                    if shaders:
                        stage = shaders[0]["stage"]
                        shader_summary = await session.call_tool(
                            "renderdoc_get_shader_summary",
                            {"capture_id": capture_id, "event_id": chosen_event, "stage": stage},
                        )
                        assert not shader_summary.isError
                        assert "text" not in shader_summary.structuredContent.get("shader", {})

                        shader_chunk = await session.call_tool(
                            "renderdoc_get_shader_code_chunk",
                            {
                                "capture_id": capture_id,
                                "event_id": chosen_event,
                                "stage": stage,
                                "start_line": 1,
                                "line_count": 200,
                            },
                        )
                        assert not shader_chunk.isError
                        assert _size_bytes(shader_chunk.structuredContent) < 40 * 1024

                    if overview_payload["capabilities"].get("shader_debugging") and chosen_draw_event is not None:
                        shader_debug = await session.call_tool(
                            "renderdoc_start_pixel_shader_debug",
                            {
                                "capture_id": capture_id,
                                "event_id": chosen_draw_event,
                                "x": 0,
                                "y": 0,
                                "state_limit": 1,
                            },
                        )
                        if not shader_debug.isError:
                            shader_debug_payload = shader_debug.structuredContent
                            shader_debug_id = shader_debug_payload["shader_debug_id"]
                            first_step_index = (
                                shader_debug_payload["states"][0]["step_index"] if shader_debug_payload["states"] else None
                            )

                            if first_step_index is None and shader_debug_payload["meta"]["has_more"]:
                                continued_debug = await session.call_tool(
                                    "renderdoc_continue_shader_debug",
                                    {
                                        "capture_id": capture_id,
                                        "shader_debug_id": shader_debug_id,
                                        "state_limit": 1,
                                    },
                                )
                                assert not continued_debug.isError
                                continued_payload = continued_debug.structuredContent
                                if continued_payload["states"]:
                                    first_step_index = continued_payload["states"][0]["step_index"]

                            if first_step_index is not None:
                                shader_step = await session.call_tool(
                                    "renderdoc_get_shader_debug_step",
                                    {
                                        "capture_id": capture_id,
                                        "shader_debug_id": shader_debug_id,
                                        "step_index": first_step_index,
                                    },
                                )
                                assert not shader_step.isError

                            end_debug = await session.call_tool(
                                "renderdoc_end_shader_debug",
                                {"capture_id": capture_id, "shader_debug_id": shader_debug_id},
                            )
                            assert not end_debug.isError
                        else:
                            assert any(
                                code in str(shader_debug.content)
                                for code in (
                                    "shader_debug_trace_unavailable",
                                    "shader_debugging_not_supported",
                                    "shader_debug_requires_draw_event",
                                )
                            )

                resources = await session.call_tool(
                    "renderdoc_list_resources",
                    {"capture_id": capture_id, "kind": "all", "limit": 50},
                )
                assert not resources.isError
                assert resources.structuredContent["meta"]["page"]["limit"] == 50
                assert _size_bytes(resources.structuredContent) < 40 * 1024
                items = resources.structuredContent["items"]

                first_texture = next((item for item in items if item["kind"] == "texture"), None)
                first_buffer = next((item for item in items if item["kind"] == "buffer"), None)

                if first_texture is not None:
                    resource_summary = await session.call_tool(
                        "renderdoc_get_resource_summary",
                        {"capture_id": capture_id, "resource_id": first_texture["resource_id"]},
                    )
                    assert not resource_summary.isError

                    pixel_history = await session.call_tool(
                        "renderdoc_get_pixel_history",
                        {
                            "capture_id": capture_id,
                            "texture_id": first_texture["resource_id"],
                            "x": 0,
                            "y": 0,
                            "limit": 100,
                        },
                    )
                    assert not pixel_history.isError

                    pixel_debug = await session.call_tool(
                        "renderdoc_debug_pixel",
                        {
                            "capture_id": capture_id,
                            "texture_id": first_texture["resource_id"],
                            "x": 0,
                            "y": 0,
                        },
                    )
                    assert not pixel_debug.isError

                    texture_preview = await session.call_tool(
                        "renderdoc_get_texture_data",
                        {
                            "capture_id": capture_id,
                            "texture_id": first_texture["resource_id"],
                            "mip_level": 0,
                            "x": 0,
                            "y": 0,
                            "width": min(4, max(1, first_texture["width"])),
                            "height": min(4, max(1, first_texture["height"])),
                        },
                    )
                    assert not texture_preview.isError

                    with tempfile.TemporaryDirectory() as temp_dir:
                        output_path = str(Path(temp_dir) / "texture.png")
                        saved_texture = await session.call_tool(
                            "renderdoc_save_texture_to_file",
                            {
                                "capture_id": capture_id,
                                "texture_id": first_texture["resource_id"],
                                "output_path": output_path,
                            },
                        )
                        assert not saved_texture.isError
                        assert Path(output_path).is_file()

                if first_buffer is not None:
                    buffer_data = await session.call_tool(
                        "renderdoc_get_buffer_data",
                        {
                            "capture_id": capture_id,
                            "buffer_id": first_buffer["resource_id"],
                            "offset": 0,
                        },
                    )
                    assert not buffer_data.isError
                    assert buffer_data.structuredContent["encoding"] == "hex"
                    assert "data" in buffer_data.structuredContent

                resource_contents = await session.read_resource("renderdoc://recent-captures")
                assert resource_contents.contents

                capture_resource = await session.read_resource("renderdoc://capture/{}/overview".format(capture_id))
                assert capture_resource.contents

                invalid_capture = await session.call_tool("renderdoc_get_capture_overview", {"capture_id": "deadbeef"})
                assert invalid_capture.isError

                invalid_event = await session.call_tool(
                    "renderdoc_get_action_summary",
                    {"capture_id": capture_id, "event_id": 999999999},
                )
                assert invalid_event.isError

                closed = await session.call_tool("renderdoc_close_capture", {"capture_id": capture_id})
                assert not closed.isError
                after_close = await session.call_tool("renderdoc_get_capture_overview", {"capture_id": capture_id})
                assert after_close.isError

    anyio.run(run_test)
