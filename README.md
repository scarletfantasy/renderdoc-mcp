# renderdoc-mcp

Language: [English](#en) | [简体中文](#zh-cn)

<a id="en"></a>
## English

`renderdoc-mcp` is a local stdio MCP server for inspecting existing RenderDoc `.rdc` captures on Windows.

It launches `qrenderdoc.exe`, installs a bundled RenderDoc Python extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`, and bridges MCP tool calls to RenderDoc's embedded Python API over a localhost socket.

This repository now exposes an AI-first v2 MCP surface:

- default responses are small
- navigation is id-based
- large results are paged or chunked
- list tools never return duplicated arrays

## Version support

- Minimum supported RenderDoc version: `1.43`
- Verified baseline: `1.43`
- Newer RenderDoc builds are supported on a best-effort forward-compatible basis with API fallbacks where practical

## Features

- `renderdoc_open_capture`
- `renderdoc_close_capture`
- `renderdoc_get_capture_overview`
- `renderdoc_get_analysis_worklist`
- `renderdoc_list_passes`
- `renderdoc_get_pass_summary`
- `renderdoc_list_timing_events`
- `renderdoc_list_actions`
- `renderdoc_get_action_summary`
- `renderdoc_get_pipeline_overview`
- `renderdoc_list_pipeline_bindings`
- `renderdoc_get_shader_summary`
- `renderdoc_get_shader_code_chunk`
- `renderdoc_list_resources`
- `renderdoc_get_resource_summary`
- `renderdoc_get_pixel_history`
- `renderdoc_debug_pixel`
- `renderdoc_get_texture_data`
- `renderdoc_get_buffer_data`
- `renderdoc_save_texture_to_file`
- `renderdoc://recent-captures`
- `renderdoc://capture/{capture_id}/overview`

## Quick start

Open a capture first:

```powershell
renderdoc_open_capture(capture_path="C:\\captures\\frame.rdc")
```

The response includes `capture_id`, `capture_path`, and a compact capture overview.

Use that `capture_id` for all follow-up tools:

```powershell
renderdoc_get_capture_overview(capture_id="<capture_id>")
```

```powershell
renderdoc_get_analysis_worklist(capture_id="<capture_id>")
```

When you are done:

```powershell
renderdoc_close_capture(capture_id="<capture_id>")
```

## Recommended AI workflow

Start with overview and worklist:

```powershell
renderdoc_get_capture_overview(capture_id="<capture_id>")
```

```powershell
renderdoc_get_analysis_worklist(
  capture_id="<capture_id>",
  focus="performance",
  limit=10
)
```

Drill into passes by parent id:

```powershell
renderdoc_list_passes(capture_id="<capture_id>", limit=50)
```

```powershell
renderdoc_list_passes(
  capture_id="<capture_id>",
  parent_pass_id="pass:81-7231",
  limit=50,
  sort_by="gpu_time"
)
```

```powershell
renderdoc_get_pass_summary(capture_id="<capture_id>", pass_id="pass:3606-5458")
```

For paged GPU timing rows:

```powershell
renderdoc_list_timing_events(
  capture_id="<capture_id>",
  pass_id="pass:3606-5458",
  limit=100,
  sort_by="gpu_time"
)
```

Navigate actions by parent event id:

```powershell
renderdoc_list_actions(capture_id="<capture_id>", limit=50)
```

```powershell
renderdoc_list_actions(
  capture_id="<capture_id>",
  parent_event_id=1234,
  limit=50,
  flags_filter="draw"
)
```

```powershell
renderdoc_get_action_summary(capture_id="<capture_id>", event_id=1234)
```

Inspect the pipeline in two steps:

```powershell
renderdoc_get_pipeline_overview(capture_id="<capture_id>", event_id=1234)
```

```powershell
renderdoc_list_pipeline_bindings(
  capture_id="<capture_id>",
  event_id=1234,
  binding_kind="descriptor_accesses",
  limit=50
)
```

Inspect shaders without dumping full disassembly:

```powershell
renderdoc_get_shader_summary(
  capture_id="<capture_id>",
  event_id=1234,
  stage="pixel"
)
```

```powershell
renderdoc_get_shader_code_chunk(
  capture_id="<capture_id>",
  event_id=1234,
  stage="pixel",
  start_line=1,
  line_count=200
)
```

Inspect resources with pagination:

```powershell
renderdoc_list_resources(
  capture_id="<capture_id>",
  kind="all",
  limit=50,
  sort_by="size"
)
```

```powershell
renderdoc_get_resource_summary(capture_id="<capture_id>", resource_id="ResourceId::123")
```

Small bounded data reads remain available:

```powershell
renderdoc_get_texture_data(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
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
  buffer_id="ResourceId::456",
  offset=0,
  size=256,
  encoding="hex"
)
```

Pixel debugging tools are still available:

```powershell
renderdoc_get_pixel_history(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
  x=512,
  y=384,
  limit=100
)
```

```powershell
renderdoc_debug_pixel(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
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

## Environment

- `RENDERDOC_QRENDERDOC_PATH`: override the default `qrenderdoc.exe` path
- `RENDERDOC_BRIDGE_TIMEOUT_SECONDS`: handshake timeout for launching qrenderdoc, default `30`
- `RENDERDOC_CAPTURE_SESSION_IDLE_SECONDS`: idle timeout for per-capture sessions, default `300`; set to `0` or a negative value to disable idle eviction

<a id="zh-cn"></a>
## 简体中文

`renderdoc-mcp` 是一个运行在 Windows 上、通过 stdio 提供服务的本地 MCP Server，用于检查现有的 RenderDoc `.rdc` capture。

它会启动 `qrenderdoc.exe`，把仓库内置的 RenderDoc Python 扩展安装到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`，并通过 localhost socket 把 MCP 调用桥接到 RenderDoc 内嵌 Python API。

当前仓库已经切到面向 AI 的 v2 接口：

- 默认返回尽量小
- 通过 id 逐层导航
- 大结果必须分页或分块
- 列表接口不再返回重复数组

## 功能列表

- `renderdoc_open_capture`
- `renderdoc_close_capture`
- `renderdoc_get_capture_overview`
- `renderdoc_get_analysis_worklist`
- `renderdoc_list_passes`
- `renderdoc_get_pass_summary`
- `renderdoc_list_timing_events`
- `renderdoc_list_actions`
- `renderdoc_get_action_summary`
- `renderdoc_get_pipeline_overview`
- `renderdoc_list_pipeline_bindings`
- `renderdoc_get_shader_summary`
- `renderdoc_get_shader_code_chunk`
- `renderdoc_list_resources`
- `renderdoc_get_resource_summary`
- `renderdoc_get_pixel_history`
- `renderdoc_debug_pixel`
- `renderdoc_get_texture_data`
- `renderdoc_get_buffer_data`
- `renderdoc_save_texture_to_file`
- `renderdoc://recent-captures`
- `renderdoc://capture/{capture_id}/overview`

## 推荐工作流

先打开 capture：

```powershell
renderdoc_open_capture(capture_path="C:\\captures\\frame.rdc")
```

先拿整体概览和工作清单：

```powershell
renderdoc_get_capture_overview(capture_id="<capture_id>")
```

```powershell
renderdoc_get_analysis_worklist(capture_id="<capture_id>", focus="performance", limit=10)
```

再按层级钻取：

```powershell
renderdoc_list_passes(capture_id="<capture_id>", limit=50)
```

```powershell
renderdoc_list_passes(
  capture_id="<capture_id>",
  parent_pass_id="pass:81-7231",
  limit=50,
  sort_by="gpu_time"
)
```

```powershell
renderdoc_get_pass_summary(capture_id="<capture_id>", pass_id="pass:3606-5458")
```

```powershell
renderdoc_list_timing_events(
  capture_id="<capture_id>",
  pass_id="pass:3606-5458",
  limit=100
)
```

```powershell
renderdoc_list_actions(capture_id="<capture_id>", limit=50)
```

```powershell
renderdoc_get_pipeline_overview(capture_id="<capture_id>", event_id=1234)
```

```powershell
renderdoc_get_shader_code_chunk(
  capture_id="<capture_id>",
  event_id=1234,
  stage="pixel",
  start_line=1,
  line_count=200
)
```

```powershell
renderdoc_list_resources(capture_id="<capture_id>", kind="all", limit=50, sort_by="size")
```

```powershell
renderdoc_get_resource_summary(capture_id="<capture_id>", resource_id="ResourceId::123")
```

```powershell
renderdoc_get_buffer_data(
  capture_id="<capture_id>",
  buffer_id="ResourceId::456",
  offset=0,
  size=256,
  encoding="hex"
)
```

完成后关闭：

```powershell
renderdoc_close_capture(capture_id="<capture_id>")
```
