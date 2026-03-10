from __future__ import annotations

import os
import sys
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
                    "renderdoc_get_action_details",
                    "renderdoc_get_pipeline_state",
                    "renderdoc_get_shader_code",
                    "renderdoc_list_resources",
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

                resource_contents = await session.read_resource("renderdoc://recent-captures")
                assert resource_contents.contents

    anyio.run(run_test)
