# renderdoc-mcp

`renderdoc-mcp` is a local stdio MCP server for inspecting existing RenderDoc `.rdc` captures on Windows.

It launches `qrenderdoc.exe`, installs a bundled RenderDoc Python extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`, and bridges MCP tool calls to RenderDoc's embedded Python API over a localhost socket.

Each call to `renderdoc_open_capture` creates a new capture session and returns a `capture_id`. Subsequent tools reuse that session through `capture_id` until you close it or it is evicted by the idle timeout.

## Version support

- Minimum supported RenderDoc version: `1.43`
- Verified baseline: `1.43`
- Newer RenderDoc builds are supported on a best-effort forward-compatible basis with API fallbacks where practical

## Features

- `renderdoc_open_capture`
- `renderdoc_close_capture`
- `renderdoc_get_capture_summary`
- `renderdoc_analyze_frame`
- `renderdoc_get_action_tree`
- `renderdoc_list_actions`
- `renderdoc_list_passes`
- `renderdoc_get_pass_details`
- `renderdoc_get_timing_data`
- `renderdoc_get_performance_hotspots`
- `renderdoc_get_action_details`
- `renderdoc_get_pipeline_state`
- `renderdoc_get_api_pipeline_state`
- `renderdoc_get_shader_code`
- `renderdoc_list_resources`
- `renderdoc_get_pixel_history`
- `renderdoc_debug_pixel`
- `renderdoc_get_texture_data`
- `renderdoc_get_buffer_data`
- `renderdoc_save_texture_to_file`
- `renderdoc://recent-captures`
- `renderdoc://capture/{capture_id}/summary`

## Quick start

Open a capture first:

```powershell
renderdoc_open_capture(capture_path="C:\\captures\\frame.rdc")
```

The response includes `capture_id`, `capture_path`, and `meta.renderdoc_version` when the bridge reports it.

Use that `capture_id` for all follow-up tools:

```powershell
renderdoc_get_capture_summary(capture_id="<capture_id>")
```

```powershell
renderdoc_analyze_frame(capture_id="<capture_id>")
```

When you are done:

```powershell
renderdoc_close_capture(capture_id="<capture_id>")
```

## Frame analysis

For a quick pass summary:

```powershell
renderdoc_analyze_frame(capture_id="<capture_id>")
```

The result includes:

- ordered top-level passes
- `pass_id`, category, confidence, reasons, and event ranges
- draw-heavy and compute-heavy pass rankings
- the tail chain leading into UI and presentation

To include a top-level pass timing summary when GPU duration counters are available:

```powershell
renderdoc_analyze_frame(
  capture_id="<capture_id>",
  include_timing_summary=true
)
```

To drill into a specific pass:

1. Call `renderdoc_list_passes(capture_id=..., limit=100)`.
2. Pick a `pass_id`.
3. Call `renderdoc_get_pass_details(capture_id=..., pass_id=...)`.

To add timing data to a pass:

```powershell
renderdoc_get_timing_data(capture_id="<capture_id>", pass_id="pass:100-250")
```

For frame-level hotspots:

```powershell
renderdoc_get_performance_hotspots(capture_id="<capture_id>")
```

If the replay device exposes `GPUCounter.EventGPUDuration`, hotspots are ranked by real GPU time. Otherwise the tool falls back to draw, dispatch, copy, and clear heuristics.

For quick pass triage, `renderdoc_list_passes` can sort by GPU time or structural metrics:

```powershell
renderdoc_list_passes(
  capture_id="<capture_id>",
  sort_by="gpu_time",
  threshold_ms=0.5,
  limit=20
)
```

If GPU timing is unavailable, `sort_by="gpu_time"` falls back to event order and reports that in the result.

## Actions and pipeline state

`renderdoc_get_action_tree` returns a tree preview of the action hierarchy:

```powershell
renderdoc_get_action_tree(capture_id="<capture_id>", max_depth=2)
```

To page through the full action list:

```powershell
renderdoc_list_actions(capture_id="<capture_id>", cursor=0, limit=100)
```

To fetch API-agnostic pipeline details:

```powershell
renderdoc_get_pipeline_state(capture_id="<capture_id>", event_id=1234)
```

To fetch API-specific pipeline details when implemented for the capture API:

```powershell
renderdoc_get_api_pipeline_state(capture_id="<capture_id>", event_id=1234)
```

On D3D12 this can include descriptor heap and root signature details. On Vulkan it can include pipeline, descriptor set or descriptor buffer, and current render pass information. If the active RenderDoc build does not expose a compatible API-specific accessor, the response reports `available: false` instead of failing the whole tool call.

To fetch shader disassembly for a specific event and stage:

```powershell
renderdoc_get_shader_code(capture_id="<capture_id>", event_id=1234, stage="pixel")
```

If a newer RenderDoc build changes the shader disassembly API surface, the response keeps the shader metadata and reports the disassembly as unavailable instead of failing the request where possible.

## Resources and pixel inspection

Start by listing resources:

```powershell
renderdoc_list_resources(capture_id="<capture_id>", kind="all")
```

Use the returned resource IDs for content inspection:

```powershell
renderdoc_get_texture_data(
  capture_id="<capture_id>",
  texture_id="1234567890",
  mip_level=0,
  x=0,
  y=0,
  width=4,
  height=4
)
```

```powershell
renderdoc_get_buffer_data(
  capture_id="<capture_id>",
  buffer_id="9876543210",
  offset=0,
  size=64
)
```

To export a texture to disk:

```powershell
renderdoc_save_texture_to_file(
  capture_id="<capture_id>",
  texture_id="1234567890",
  output_path="C:\\captures\\albedo.png"
)
```

For pixel history against a specific texture and subresource:

```powershell
renderdoc_get_pixel_history(
  capture_id="<capture_id>",
  texture_id="1234567890",
  x=512,
  y=384
)
```

To collapse that history into a draw-centric impact summary:

```powershell
renderdoc_debug_pixel(
  capture_id="<capture_id>",
  texture_id="1234567890",
  x=512,
  y=384
)
```

## Install

```powershell
uv sync --group dev
uv run renderdoc-install-extension
```

The installer always copies the bundled extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`.

By default it also ensures that `%APPDATA%\qrenderdoc\UI.config` contains `renderdoc_mcp_bridge` inside `AlwaysLoad_Extensions`.

Behavior details:

- The installer only changes the `AlwaysLoad_Extensions` key.
- If `renderdoc_mcp_bridge` is already present, it leaves `UI.config` untouched.
- It does not rewrite unrelated keys.

To install the extension without modifying `UI.config`:

```powershell
uv run renderdoc-install-extension --no-always-load
```

You can also disable the `UI.config` update for both manual installs and automatic startup installs:

```powershell
$env:RENDERDOC_INSTALL_ALWAYS_LOAD = "0"
```

## Run

```powershell
uv run renderdoc-mcp
```

Optional environment variables:

- `RENDERDOC_QRENDERDOC_PATH`: absolute path to `qrenderdoc.exe`
- `RENDERDOC_BRIDGE_TIMEOUT_SECONDS`: handshake timeout, default `30`
- `RENDERDOC_CAPTURE_SESSION_IDLE_SECONDS`: idle timeout in seconds for per-capture sessions, default `300`; set to `0` or a negative value to disable idle eviction
- `RENDERDOC_INSTALL_ALWAYS_LOAD`: `0/false/no/off` to skip editing `UI.config` during extension installation

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
