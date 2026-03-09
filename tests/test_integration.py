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
                    "renderdoc_list_actions",
                    "renderdoc_get_action_details",
                    "renderdoc_get_pipeline_state",
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

                resources = await session.call_tool(
                    "renderdoc_list_resources",
                    {"capture_path": capture_path, "kind": "all"},
                )
                assert not resources.isError
                assert resources.structuredContent["result"]["count"] > 0

                resource_contents = await session.read_resource("renderdoc://recent-captures")
                assert resource_contents.contents

    anyio.run(run_test)
