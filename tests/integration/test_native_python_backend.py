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
def test_native_python_backend_stdio_smoke() -> None:
    capture_path = _find_capture()
    module_dir_raw = str(os.environ.get("RENDERDOC_NATIVE_MODULE_DIR", "") or "").strip()
    if capture_path is None:
        pytest.skip("No local .rdc capture was found for integration testing.")
    if not module_dir_raw:
        pytest.skip("RENDERDOC_NATIVE_MODULE_DIR is not configured.")

    module_dir = Path(module_dir_raw)
    if not (module_dir / "renderdoc.pyd").is_file():
        pytest.skip("RENDERDOC_NATIVE_MODULE_DIR does not contain renderdoc.pyd.")

    async def run_test() -> None:
        env = os.environ.copy()
        env["RENDERDOC_BACKEND"] = "native_python"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "renderdoc_mcp"],
            env=env,
        )

        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                opened = await session.call_tool("renderdoc_open_capture", {"capture_path": capture_path})
                assert not opened.isError
                payload = opened.structuredContent
                assert payload is not None
                assert payload["meta"]["backend"] == "native_python"

                capture_id = payload["capture_id"]
                overview = await session.call_tool("renderdoc_get_capture_overview", {"capture_id": capture_id})
                assert not overview.isError
                assert overview.structuredContent["meta"]["backend"] == "native_python"

                closed = await session.call_tool("renderdoc_close_capture", {"capture_id": capture_id})
                assert not closed.isError
                assert closed.structuredContent["meta"]["backend"] == "native_python"

    anyio.run(run_test)
