# renderdoc-mcp

`renderdoc-mcp` is a local stdio MCP server for inspecting existing RenderDoc `.rdc` captures on Windows.

It launches `qrenderdoc.exe`, installs a small RenderDoc Python extension into `%APPDATA%\qrenderdoc\extensions`, and bridges MCP tool calls to RenderDoc's embedded Python API over a localhost socket.

## Features

- `renderdoc_get_capture_summary`
- `renderdoc_analyze_frame`
- `renderdoc_list_actions`
- `renderdoc_list_passes`
- `renderdoc_get_pass_details`
- `renderdoc_get_action_details`
- `renderdoc_get_pipeline_state`
- `renderdoc_list_resources`
- `renderdoc://recent-captures`
- `renderdoc://capture/{base64url_path}/summary`

## Analysis model

`renderdoc-mcp` now exposes two layers of tooling:

- Low-level primitives for action trees, event details, pipeline state, and resources.
- High-level frame analysis that groups the capture into top-level passes, ranks draw-heavy and compute-heavy hotspots, and highlights the tail UI/present chain.

The pass classifier is intentionally engine-agnostic. It uses action structure, outputs, draw or dispatch counts, event boundaries, and naming hints when available. Naming hints are advisory only and low weight.

## High-level analysis flow

For a quick pass summary, start with:

```powershell
renderdoc_analyze_frame(capture_path="C:\\captures\\frame.rdc")
```

The result includes:

- ordered top-level passes
- `pass_id`, category, confidence, reasons, and event ranges
- draw-heavy and compute-heavy pass rankings
- the tail chain leading into UI and presentation

To drill into a specific pass:

1. Call `renderdoc_list_passes(capture_path=..., limit=100)`.
2. Pick a `pass_id`.
3. Call `renderdoc_get_pass_details(capture_path=..., pass_id=...)`.

`renderdoc_get_pass_details` returns the nested pass structure, representative events, output summaries, and child pass breakdown.

## Low-level action access

`renderdoc_list_actions` keeps the legacy tree preview by default. When no `cursor` or `limit` is supplied, it returns a tree preview capped at `500` visible nodes and includes `has_more` and `next_cursor`.

To page through the full action list without truncation, pass `cursor` and `limit`:

```powershell
renderdoc_list_actions(capture_path="C:\\captures\\frame.rdc", cursor=0, limit=100)
```

Paged action results use a flat preorder list with `depth`, `parent_event_id`, `has_more`, and `next_cursor`.

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
