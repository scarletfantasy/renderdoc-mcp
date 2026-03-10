from __future__ import annotations

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


@pytest.mark.integration
def test_stdio_tools_and_resources() -> None:
    capture_path = _find_capture()
    if capture_path is None:
        pytest.skip("No local .rdc capture was found for integration testing.")

    async def run_test() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "renderdoc_mcp"],
            env=os.environ.copy(),
        )

        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                tool_names = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "renderdoc_get_capture_summary",
                    "renderdoc_analyze_frame",
                    "renderdoc_list_actions",
                    "renderdoc_list_passes",
                    "renderdoc_get_pass_details",
                    "renderdoc_get_timing_data",
                    "renderdoc_get_performance_hotspots",
                    "renderdoc_get_action_details",
                    "renderdoc_get_pipeline_state",
                    "renderdoc_get_shader_code",
                    "renderdoc_list_resources",
                    "renderdoc_get_pixel_history",
                    "renderdoc_debug_pixel",
                    "renderdoc_get_texture_data",
                    "renderdoc_get_buffer_data",
                    "renderdoc_save_texture_to_file",
                }.issubset(tool_names)

                summary = await session.call_tool("renderdoc_get_capture_summary", {"capture_path": capture_path})
                assert not summary.isError
                summary_payload = summary.structuredContent
                assert summary_payload is not None
                assert summary_payload["error"] is None

                actions = await session.call_tool("renderdoc_list_actions", {"capture_path": capture_path, "max_depth": 1})
                assert not actions.isError
                action_tree = actions.structuredContent["result"]["actions"]
                assert action_tree
                assert actions.structuredContent["result"]["returned_count"] > 0

                paged_actions = await session.call_tool(
                    "renderdoc_list_actions",
                    {"capture_path": capture_path, "cursor": 0, "limit": 25},
                )
                assert not paged_actions.isError
                assert paged_actions.structuredContent["result"]["returned_count"] > 0
                assert paged_actions.structuredContent["result"]["page_mode"] == "flat_preorder"

                analysis = await session.call_tool("renderdoc_analyze_frame", {"capture_path": capture_path})
                assert not analysis.isError
                pass_payload = analysis.structuredContent["result"]
                assert pass_payload["pass_count"] > 0
                assert any(
                    item["category"] in {"geometry", "unknown"}
                    for item in pass_payload["passes"]
                )
                assert any(
                    item["category"] == "presentation"
                    for item in pass_payload["passes"]
                )

                listed_passes = await session.call_tool(
                    "renderdoc_list_passes",
                    {"capture_path": capture_path, "limit": 10},
                )
                assert not listed_passes.isError
                assert listed_passes.structuredContent["result"]["returned_count"] > 0
                first_pass_id = listed_passes.structuredContent["result"]["passes"][0]["pass_id"]

                pass_details = await session.call_tool(
                    "renderdoc_get_pass_details",
                    {"capture_path": capture_path, "pass_id": first_pass_id},
                )
                assert not pass_details.isError
                assert pass_details.structuredContent["result"]["pass_id"] == first_pass_id

                timing = await session.call_tool(
                    "renderdoc_get_timing_data",
                    {"capture_path": capture_path, "pass_id": first_pass_id},
                )
                assert not timing.isError
                assert timing.structuredContent["result"]["pass"]["pass_id"] == first_pass_id

                hotspots = await session.call_tool(
                    "renderdoc_get_performance_hotspots",
                    {"capture_path": capture_path},
                )
                assert not hotspots.isError
                assert "basis" in hotspots.structuredContent["result"]

                first_event = action_tree[0]["event_id"]
                details = await session.call_tool(
                    "renderdoc_get_action_details",
                    {"capture_path": capture_path, "event_id": first_event},
                )
                assert not details.isError
                assert details.structuredContent["result"]["action"]["event_id"] == first_event

                pipeline = await session.call_tool(
                    "renderdoc_get_pipeline_state",
                    {"capture_path": capture_path, "event_id": first_event},
                )
                assert not pipeline.isError
                assert pipeline.structuredContent["result"]["event_id"] == first_event

                shader_probe_actions = await session.call_tool(
                    "renderdoc_list_actions",
                    {"capture_path": capture_path, "cursor": 0, "limit": 100},
                )
                assert not shader_probe_actions.isError

                shader_event = None
                shader_stage = None
                for item in shader_probe_actions.structuredContent["result"]["actions"]:
                    if not {"draw", "dispatch"}.intersection(item["flags"]):
                        continue

                    candidate = await session.call_tool(
                        "renderdoc_get_pipeline_state",
                        {"capture_path": capture_path, "event_id": item["event_id"]},
                    )
                    assert not candidate.isError
                    shaders = candidate.structuredContent["result"]["pipeline"]["shaders"]
                    if shaders:
                        shader_event = item["event_id"]
                        shader_stage = shaders[0]["stage"]
                        break

                if shader_event is not None and shader_stage is not None:
                    shader_code = await session.call_tool(
                        "renderdoc_get_shader_code",
                        {
                            "capture_path": capture_path,
                            "event_id": shader_event,
                            "stage": shader_stage,
                        },
                    )
                    assert not shader_code.isError
                    assert shader_code.structuredContent["result"]["event_id"] == shader_event
                    assert shader_code.structuredContent["result"]["shader"]["stage"] == shader_stage
                    assert shader_code.structuredContent["result"]["disassembly"]["text"]

                resources = await session.call_tool(
                    "renderdoc_list_resources",
                    {"capture_path": capture_path, "kind": "all"},
                )
                assert not resources.isError
                assert resources.structuredContent["result"]["count"] > 0

                textures = resources.structuredContent["result"]["textures"]
                buffers = resources.structuredContent["result"]["buffers"]

                first_texture = next(
                    (
                        item
                        for item in textures
                        if item["resource_id"] and item["width"] > 0 and item["height"] > 0
                    ),
                    None,
                )
                if first_texture is not None:
                    pixel_history = await session.call_tool(
                        "renderdoc_get_pixel_history",
                        {
                            "capture_path": capture_path,
                            "texture_id": first_texture["resource_id"],
                            "x": 0,
                            "y": 0,
                        },
                    )
                    assert not pixel_history.isError
                    assert pixel_history.structuredContent["result"]["texture"]["resource_id"] == first_texture["resource_id"]

                    pixel_debug = await session.call_tool(
                        "renderdoc_debug_pixel",
                        {
                            "capture_path": capture_path,
                            "texture_id": first_texture["resource_id"],
                            "x": 0,
                            "y": 0,
                        },
                    )
                    assert not pixel_debug.isError
                    assert pixel_debug.structuredContent["result"]["texture"]["resource_id"] == first_texture["resource_id"]

                    texture_preview = await session.call_tool(
                        "renderdoc_get_texture_data",
                        {
                            "capture_path": capture_path,
                            "texture_id": first_texture["resource_id"],
                            "mip_level": 0,
                            "x": 0,
                            "y": 0,
                            "width": min(4, first_texture["width"]),
                            "height": min(4, first_texture["height"]),
                        },
                    )
                    assert not texture_preview.isError
                    assert texture_preview.structuredContent["result"]["texture"]["resource_id"] == first_texture["resource_id"]

                    with tempfile.TemporaryDirectory() as temp_dir:
                        output_path = str(Path(temp_dir) / "texture.png")
                        saved_texture = await session.call_tool(
                            "renderdoc_save_texture_to_file",
                            {
                                "capture_path": capture_path,
                                "texture_id": first_texture["resource_id"],
                                "output_path": output_path,
                            },
                        )
                        assert not saved_texture.isError
                        assert Path(output_path).is_file()

                first_buffer = next((item for item in buffers if item["resource_id"] and item["byte_size"] > 0), None)
                if first_buffer is not None:
                    buffer_size = min(32, first_buffer["byte_size"])
                    buffer_data = await session.call_tool(
                        "renderdoc_get_buffer_data",
                        {
                            "capture_path": capture_path,
                            "buffer_id": first_buffer["resource_id"],
                            "offset": 0,
                            "size": buffer_size,
                        },
                    )
                    assert not buffer_data.isError
                    assert buffer_data.structuredContent["result"]["buffer"]["resource_id"] == first_buffer["resource_id"]

                resource_contents = await session.read_resource("renderdoc://recent-captures")
                assert resource_contents.contents

    anyio.run(run_test)
