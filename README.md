# renderdoc-mcp

`renderdoc-mcp` is a local stdio MCP server for inspecting existing RenderDoc `.rdc` captures on Windows.

It launches `qrenderdoc.exe`, installs a small RenderDoc Python extension into `%APPDATA%\qrenderdoc\extensions`, and bridges MCP tool calls to RenderDoc's embedded Python API over a localhost socket.

## Features

- `renderdoc_get_capture_summary`
- `renderdoc_list_actions`
- `renderdoc_get_action_details`
- `renderdoc_get_pipeline_state`
- `renderdoc_list_resources`
- `renderdoc://recent-captures`
- `renderdoc://capture/{base64url_path}/summary`

## Install

```powershell
uv sync --group dev
uv run renderdoc-install-extension
```

The installer copies the bundled extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge` and ensures it is listed in `AlwaysLoad_Extensions`.

## Run

```powershell
uv run renderdoc-mcp
```

Optional environment variables:

- `RENDERDOC_QRENDERDOC_PATH`: absolute path to `qrenderdoc.exe`
- `RENDERDOC_BRIDGE_TIMEOUT_SECONDS`: handshake timeout, default `30`

## Claude Desktop example

```json
{
  "mcpServers": {
    "renderdoc": {
      "command": "uv",
      "args": ["run", "--directory", "<path-to-renderdoc-mcp>", "renderdoc-mcp"]
    }
  }
}
```

Replace `<path-to-renderdoc-mcp>` with your local checkout path.

## Tests

```powershell
uv run pytest
uv run pytest -m integration
```
