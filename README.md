# renderdoc-mcp

[![Featured by Awesome REA](https://raw.githubusercontent.com/reacher-z/Awesome-REA/main/assets/featured-by-awesome-rea-inline.svg)](https://github.com/reacher-z/Awesome-REA)

Language: [English](#en) | [简体中文](#zh-cn)

<a id="en"></a>
## English

`renderdoc-mcp` is a local stdio MCP server for inspecting existing RenderDoc `.rdc` captures on Windows.

By default it launches `qrenderdoc.exe`, installs a bundled RenderDoc Python extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`, and bridges MCP tool calls to RenderDoc's embedded Python API over a localhost socket.

It also supports an optional `native_python` backend that runs a standalone `renderdoc.pyd` inside a helper Python process. This backend requires a source-built RenderDoc Python module and is not available from the default RenderDoc installer.

This repository now exposes an AI-first v2 MCP surface:

- default responses are small
- navigation is id-based
- large results are paged or chunked
- list tools never return duplicated arrays

## Version support

- Legacy minimum RenderDoc version: `1.36`
- Verified baseline: `1.43`
- RenderDoc `1.36` support is best-effort for older captures that require that replay version. Core capture opening, overview, action/resource navigation, and basic pipeline inspection are expected to work; newer RenderDoc APIs such as timing counters, descriptor details, shader disassembly, or shader debugging may report unavailable through capability flags or per-tool `available: false` payloads.
- Newer RenderDoc builds are supported on a best-effort forward-compatible basis with API fallbacks where practical

## Features

- `renderdoc_open_capture`
- `renderdoc_close_capture`
- `renderdoc_list_open_captures`
- `renderdoc_get_server_status`
- `renderdoc_get_capture_overview`
- `renderdoc_get_analysis_worklist`
- `renderdoc_list_passes`
- `renderdoc_get_pass_summary`
- `renderdoc_list_timing_events`
- `renderdoc_list_actions`
- `renderdoc_search_actions`
- `renderdoc_get_action_summary`
- `renderdoc_get_pipeline_overview`
- `renderdoc_get_event_dossier`
- `renderdoc_get_event_dossiers`
- `renderdoc_list_pipeline_bindings`
- `renderdoc_get_shader_summary`
- `renderdoc_get_shader_code_chunk`
- `renderdoc_search_shader_code`
- `renderdoc_list_resources`
- `renderdoc_get_resource_summary`
- `renderdoc_list_resource_usages`
- `renderdoc_search_resource_bindings`
- `renderdoc_get_pixel_history`
- `renderdoc_debug_pixel`
- `renderdoc_trace_bad_pixel`
- `renderdoc_probe_texture_regions`
- `renderdoc_start_pixel_shader_debug`
- `renderdoc_start_compute_shader_debug`
- `renderdoc_continue_shader_debug`
- `renderdoc_analyze_shader_debug`
- `renderdoc_get_shader_debug_step`
- `renderdoc_end_shader_debug`
- `renderdoc_get_texture_data`
- `renderdoc_get_buffer_data`
- `renderdoc_create_investigation`
- `renderdoc_add_investigation_capture`
- `renderdoc_set_investigation_focus`
- `renderdoc_pin_investigation_evidence`
- `renderdoc_get_investigation_summary`
- `renderdoc_list_investigations`
- `renderdoc_close_investigation`
- `renderdoc_compare_events`
- `renderdoc_compare_texture_regions`
- `renderdoc_save_texture_to_file`
- `renderdoc://recent-captures`
- `renderdoc://capture/{capture_id}/overview`

## Quick start

If setup is uncertain, inspect the server without launching replay:

```powershell
renderdoc_get_server_status()
```

Open a capture first:

```powershell
renderdoc_open_capture(capture_path="C:\\captures\\frame.rdc")
```

The response includes `capture_id`, `capture_path`, and a compact capture overview. Opening the same normalized path again reuses the same bridge and `capture_id`; inspect retained sessions with `renderdoc_list_open_captures`.

`renderdoc_get_capture_overview` also reports capability flags such as `shader_debugging`, which indicates whether the active replay device can create RenderDoc shader debug traces for this capture. GPU timing support is checked without collecting the full counter set: `timing_data_collected=false` remains until a timing or performance tool first needs those rows, after which the result is cached for the capture.

Use that `capture_id` for all follow-up tools:

```powershell
renderdoc_get_capture_overview(capture_id="<capture_id>")
```

```powershell
renderdoc_get_analysis_worklist(capture_id="<capture_id>")
```

Keep the session open across related turns. When the investigation is explicitly done:

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

`sort_by="gpu_time"` uses replay-derived GPU timing. Treat it as a noisy hint for ranking, not a stable correctness baseline across runs.

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

`gpu_time_ms` comes from RenderDoc replay counters. The same `.rdc` can produce different values across runs or sessions, so timing is best used for hotspot guidance and within-run ordering.

Use `renderdoc_list_actions` for direct children. Use recursive search when draws are nested under unknown marker depth:

```powershell
renderdoc_search_actions(capture_id="<capture_id>", flags_filter="draw", query="BasePass", limit=50)
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

Once an event is known, prefer one bounded dossier over separate action, pass, pipeline, shader, and binding calls:

```powershell
renderdoc_get_event_dossier(
  capture_id="<capture_id>",
  event_id=1234,
  binding_kinds=["output_targets", "shaders", "read_only_resources", "read_write_resources"],
  binding_limit=50
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
renderdoc_search_shader_code(
  capture_id="<capture_id>",
  event_id=1234,
  stage="pixel",
  query="load|store|sample|atomic|discard",
  regex=true,
  context_lines=2
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

```powershell
renderdoc_list_resource_usages(
  capture_id="<capture_id>",
  resource_id="ResourceId::123",
  usage_kind="all",
  limit=50
)
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

Single and batch dossiers enforce a global binding/response budget. A batch that stops early reports `unprocessed_event_ids`, which can be submitted in the next bounded call.

`renderdoc_list_resource_usages` is the fast structural RT/depth writer and copy/resolve relationship index (`rt_texture_v1`); it does not claim complete shader read/write coverage. Use the bounded cross-API pipeline scan for shader-visible resources and constant blocks:

```powershell
renderdoc_search_resource_bindings(
  capture_id="<capture_id>",
  resource_id="ResourceId::123",
  scan_limit=100,
  match_limit=50
)
```

The binding scan batches compatible replay-controller event transitions and caches per-resource/event matches. `meta.scan.performance` reports whether a page used batched replay, the compatibility fallback, or only cached rows.

To locate sparse or unexpectedly active areas before choosing a pixel to debug:

```powershell
renderdoc_probe_texture_regions(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
  x=0,
  y=0,
  width=128,
  height=128,
  channel_mode="local_outlier",
  threshold=0.5
)
```

Besides threshold modes (`luma`, `max_rgb`, `alpha`, and `any`), `channel_mode` supports `nan_inf`, `local_outlier`, and `gradient` for common correctness searches without exporting a full texture.
If `width` and `height` are omitted, the probe defaults to 64×64; explicit windows are limited to 128×128 and 16,384 pixels.
Exact sampled grids are retained in a bounded per-capture pixel cache, so repeated probes or a follow-up `renderdoc_get_texture_data` call for the same subresource and rectangle avoid another `PickPixel` sweep.

Pixel debugging tools are still available:

```powershell
renderdoc_trace_bad_pixel(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
  x=512,
  y=384
)
```

`renderdoc_trace_bad_pixel` is the recommended first call for "why is this pixel wrong?" because it stitches together pixel history, the most relevant events and passes, pipeline context, and a best-effort one-step shader debug when supported.

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

`renderdoc_debug_pixel` remains a compact low-level pixel-history summary. For actual RenderDoc shader single-step debugging, use the session-based tools when `capabilities.shader_debugging` is `true`:

```powershell
renderdoc_start_pixel_shader_debug(
  capture_id="<capture_id>",
  event_id=1234,
  x=512,
  y=384,
  state_limit=64
)
```

```powershell
renderdoc_start_compute_shader_debug(
  capture_id="<capture_id>",
  event_id=8659,
  group_x=492,
  group_y=262,
  group_z=0,
  thread_x=1,
  thread_y=0,
  thread_z=0,
  state_limit=64
)
```

```powershell
renderdoc_continue_shader_debug(
  capture_id="<capture_id>",
  shader_debug_id="<shader_debug_id>",
  state_limit=64
)
```

For root-cause triage, summarize the remaining trace server-side and fetch only interesting steps in detail:

```powershell
renderdoc_analyze_shader_debug(
  capture_id="<capture_id>",
  shader_debug_id="<shader_debug_id>",
  max_steps=4096,
  max_interesting_steps=32
)
```

```powershell
renderdoc_get_shader_debug_step(
  capture_id="<capture_id>",
  shader_debug_id="<shader_debug_id>",
  step_index=0
)
```

```powershell
renderdoc_end_shader_debug(
  capture_id="<capture_id>",
  shader_debug_id="<shader_debug_id>"
)
```

For multi-turn or regression work, create an investigation, persist the current focus/evidence, and compare events or texture regions without dumping both raw payloads. Investigation state is in-memory and does not keep a closed capture alive.

```powershell
renderdoc_create_investigation(name="GI regression", capture_ids=["<baseline_id>", "<candidate_id>"])
renderdoc_set_investigation_focus(
  investigation_id="<investigation_id>",
  capture_id="<candidate_id>",
  event_id=1250,
  texture_id="ResourceId::123",
  x=512,
  y=384
)
renderdoc_get_investigation_summary(investigation_id="<investigation_id>")
renderdoc_compare_events(
  baseline_capture_id="<baseline_id>", baseline_event_id=1200,
  candidate_capture_id="<candidate_id>", candidate_event_id=1250
)
renderdoc_compare_texture_regions(
  baseline_capture_id="<baseline_id>", baseline_texture_id="ResourceId::100",
  candidate_capture_id="<candidate_id>", candidate_texture_id="ResourceId::123",
  x=496, y=368, width=32, height=32
)
```

Baseline and candidate reads run concurrently when they belong to different open capture sessions; comparisons within one capture remain serialized through that capture's bridge.

If a later turn no longer has the investigation id, recover active ids and focus with `renderdoc_list_investigations()`.

## Install

```powershell
uv sync --group dev
uv run renderdoc-install-extension
```

The installer always copies the bundled extension into `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`.

Installation is serialized across processes and replaces the extension as one complete snapshot. Generated Python caches are excluded, and a modified or incomplete installed snapshot is repaired automatically on the next install.

By default it also ensures that `%APPDATA%\qrenderdoc\UI.config` contains `renderdoc_mcp_bridge` inside `AlwaysLoad_Extensions`.

To install the extension without modifying `UI.config`:

```powershell
uv run renderdoc-install-extension --no-always-load
```

You can also disable the `UI.config` update for both manual installs and automatic startup installs:

```powershell
$env:RENDERDOC_INSTALL_ALWAYS_LOAD = "0"
```

## Benchmark

Run the fixed AI-first workflow benchmark against a real `.rdc` capture:

```powershell
uv run renderdoc-benchmark-ai-surface --capture "C:\captures\sample.rdc"
```

The benchmark:

- opens the capture
- exercises history-derived scenarios for nested action discovery, correctness dossiers, resource attribution, shader root cause, continuation reuse, and event regression
- measures response bytes, approximate token cost, and elapsed time
- computes `payload_score`, `latency_score`, and `composite_score`
- checks scenario call budgets, an ordinary-workflow budget of 20 calls, and a 256 KiB maximum single response
- appends a JSONL record to `benchmarks/ai_surface_history.jsonl`
- can optionally compare the current result against an older git ref such as `HEAD^`

Scoring uses the interactive workflow only, excluding `open_capture` and `close_capture`. Higher is better. `composite_score` weights payload efficiency at `85%` and latency at `15%`.

The workflow still relies on replay-derived GPU timing for worklist and timing-oriented ranking. Expect some run-to-run noise, and treat `compare-ref` deltas as directional signals rather than strict regression thresholds.

Useful options:

```powershell
uv run renderdoc-benchmark-ai-surface `
  --capture "C:\captures\sample.rdc" `
  --capture-label "sample-capture" `
  --note "after registry/timing refactor"
```

To compare the current AI-first surface against the previous commit in one run:

```powershell
uv run renderdoc-benchmark-ai-surface `
  --capture "C:\captures\sample.rdc" `
  --capture-label "sample-capture" `
  --compare-ref "HEAD^"
```

## Run

```powershell
uv run renderdoc-mcp
```

## Environment

- `RENDERDOC_BACKEND`: backend to use, `qrenderdoc` (default) or `native_python`
- `RENDERDOC_QRENDERDOC_PATH`: override the default `qrenderdoc.exe` path
- `RENDERDOC_BRIDGE_TIMEOUT_SECONDS`: handshake timeout for launching the configured backend, default `30`
- `RENDERDOC_CAPTURE_SESSION_IDLE_SECONDS`: idle timeout for per-capture sessions, default `300`; set to `0` or a negative value to disable idle eviction
- `RENDERDOC_CAPTURE_MAX_SESSIONS`: maximum retained capture sessions, default `8`; least-recently-used idle sessions are closed first, and `0` or a negative value disables the limit
- `RENDERDOC_NATIVE_MODULE_DIR`: directory containing a standalone source-built `renderdoc.pyd` when `RENDERDOC_BACKEND=native_python`
- `RENDERDOC_NATIVE_PYTHON_EXE`: Python executable used for the helper process in `native_python` mode; defaults to the current Python executable
- `RENDERDOC_NATIVE_DLL_DIR`: DLL directory for the native helper; defaults to `RENDERDOC_NATIVE_MODULE_DIR`

The server also runs a lightweight background janitor for idle sessions, so an unused capture is closed even when no later MCP request arrives.

## Development

```powershell
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run mypy
uv build
```

Tests that need a locally installed RenderDoc build and a replayable `.rdc` capture are marked `integration` and skip when those prerequisites are unavailable. CI runs the remaining suite on Python 3.10, 3.12, and 3.14 on Windows, plus lint, type, coverage, and package-build checks.

<a id="zh-cn"></a>
## 简体中文

`renderdoc-mcp` 是一个运行在 Windows 上、通过 stdio 提供服务的本地 MCP Server，用于检查现有的 RenderDoc `.rdc` capture。

它会启动 `qrenderdoc.exe`，把仓库内置的 RenderDoc Python 扩展安装到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`，并通过 localhost socket 把 MCP 调用桥接到 RenderDoc 内嵌 Python API。

当前仓库已经切到面向 AI 的 v2 接口：

- 默认返回尽量小
- 通过 id 逐层导航
- 大结果必须分页或分块
- 列表接口不再返回重复数组

## 版本支持

- 旧版最低 RenderDoc 版本：`1.36`
- 已验证基线：`1.43`
- RenderDoc `1.36` 兼容主要用于必须用旧版回放的 capture。打开 capture、overview、action/resource 导航、基础 pipeline 检查应尽量可用；GPU timing、descriptor 细节、shader 反汇编、shader debug 等较新的 API 如果旧版不支持，会通过 capability flag 或单个工具的 `available: false` 返回降级结果。
- 更新版本的 RenderDoc 按 best-effort 方式继续支持，并在可行处走 API fallback。

## 功能列表

- `renderdoc_open_capture`
- `renderdoc_close_capture`
- `renderdoc_list_open_captures`
- `renderdoc_get_server_status`
- `renderdoc_get_capture_overview`
- `renderdoc_get_analysis_worklist`
- `renderdoc_list_passes`
- `renderdoc_get_pass_summary`
- `renderdoc_list_timing_events`
- `renderdoc_list_actions`
- `renderdoc_search_actions`
- `renderdoc_get_action_summary`
- `renderdoc_get_pipeline_overview`
- `renderdoc_get_event_dossier`
- `renderdoc_get_event_dossiers`
- `renderdoc_list_pipeline_bindings`
- `renderdoc_get_shader_summary`
- `renderdoc_get_shader_code_chunk`
- `renderdoc_search_shader_code`
- `renderdoc_list_resources`
- `renderdoc_get_resource_summary`
- `renderdoc_list_resource_usages`
- `renderdoc_search_resource_bindings`
- `renderdoc_get_pixel_history`
- `renderdoc_debug_pixel`
- `renderdoc_trace_bad_pixel`
- `renderdoc_probe_texture_regions`
- `renderdoc_start_pixel_shader_debug`
- `renderdoc_start_compute_shader_debug`
- `renderdoc_continue_shader_debug`
- `renderdoc_analyze_shader_debug`
- `renderdoc_get_shader_debug_step`
- `renderdoc_end_shader_debug`
- `renderdoc_get_texture_data`
- `renderdoc_get_buffer_data`
- `renderdoc_create_investigation`
- `renderdoc_add_investigation_capture`
- `renderdoc_set_investigation_focus`
- `renderdoc_pin_investigation_evidence`
- `renderdoc_get_investigation_summary`
- `renderdoc_list_investigations`
- `renderdoc_close_investigation`
- `renderdoc_compare_events`
- `renderdoc_compare_texture_regions`
- `renderdoc_save_texture_to_file`
- `renderdoc://recent-captures`
- `renderdoc://capture/{capture_id}/overview`

## 推荐工作流

如果安装状态不确定，先做不会启动 replay 的只读检查：

```powershell
renderdoc_get_server_status()
```

先打开 capture：

```powershell
renderdoc_open_capture(capture_path="C:\\captures\\frame.rdc")
```

同一路径会复用已有 bridge 和 `capture_id`。相关的多轮分析中持续复用该 id，可通过 `renderdoc_list_open_captures` 恢复当前会话；不要在每轮结束时关闭 capture。打开 capture 时只检查 GPU timing 能力，不立即采集整帧 counter；`timing_data_collected=false` 会持续到 timing/performance 工具首次真正需要数据，之后结果会按 capture 缓存。

先拿整体概览和工作清单：

```powershell
renderdoc_get_capture_overview(capture_id="<capture_id>")
```

```powershell
renderdoc_get_analysis_worklist(capture_id="<capture_id>", focus="performance", limit=10)
```

正确性问题改用 `focus="correctness"`。它会优先给出晚帧 writer/copy 候选，再沿事件证据继续检查。

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
renderdoc_search_actions(
  capture_id="<capture_id>",
  query="BasePass",
  flags_filter="draw",
  limit=50
)
```

`renderdoc_list_actions` 只浏览直接子节点；marker 深度未知时优先用递归的 `renderdoc_search_actions`。确定事件后，用一次有界 dossier 合并 action、pass、pipeline 和所需 bindings：

```powershell
renderdoc_get_event_dossier(
  capture_id="<capture_id>",
  event_id=1234,
  binding_kinds=["output_targets", "shaders", "read_only_resources", "read_write_resources"],
  binding_limit=50
)
```

单个和批量 dossier 都有全局 binding/响应预算；批量结果若提前停止，会返回 `unprocessed_event_ids`，下一次继续提交这些 id 即可。

```powershell
renderdoc_search_shader_code(
  capture_id="<capture_id>",
  event_id=1234,
  stage="pixel",
  query="load|store|sample|atomic|discard",
  regex=true,
  context_lines=2
)
```

只在需要完整上下文时再用 `renderdoc_get_shader_code_chunk` 分块读取反汇编。

```powershell
renderdoc_start_pixel_shader_debug(
  capture_id="<capture_id>",
  event_id=1234,
  x=512,
  y=384,
  state_limit=64
)
```

拿到 `shader_debug_id` 后，用 `renderdoc_analyze_shader_debug(max_steps=4096)` 在服务端汇总剩余 trace，再只读取少量关键 step；结束时调用 `renderdoc_end_shader_debug`。

```powershell
renderdoc_list_resources(capture_id="<capture_id>", kind="all", limit=50, sort_by="size")
```

```powershell
renderdoc_get_resource_summary(capture_id="<capture_id>", resource_id="ResourceId::123")
```

```powershell
renderdoc_list_resource_usages(
  capture_id="<capture_id>",
  resource_id="ResourceId::123",
  usage_kind="all",
  limit=50
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

`renderdoc_list_resource_usages` 是快速的结构化 RT/depth/copy/resolve 索引（`rt_texture_v1`），不宣称覆盖所有 shader read/write。检查 shader 可见资源或 constant block 时使用有界 pipeline 扫描：

```powershell
renderdoc_search_resource_bindings(
  capture_id="<capture_id>",
  resource_id="ResourceId::123",
  scan_limit=100,
  match_limit=50
)
```

兼容的 RenderDoc 版本会在一个 replay 批次内切换并扫描多个事件，同时缓存 resource/event 匹配；`meta.scan.performance` 会标明使用了批量 replay、兼容回退还是纯缓存结果。

在选择要调试的像素前，可以先扫描稀疏或异常活跃区域：

```powershell
renderdoc_probe_texture_regions(
  capture_id="<capture_id>",
  texture_id="ResourceId::123",
  x=0,
  y=0,
  width=128,
  height=128,
  channel_mode="local_outlier",
  threshold=0.5
)
```

除阈值模式外，`channel_mode` 还支持 `nan_inf`、`local_outlier` 和 `gradient`，可直接筛查非有限值、局部离群与边缘突变。
省略 `width`、`height` 时默认扫描 64×64；显式窗口最多 128×128，且总像素数不能超过 16,384。
采样网格保存在有界的 capture 内像素缓存中；同一 subresource 和矩形上的重复 probe，或紧接着调用 `renderdoc_get_texture_data`，不会再次执行整块 `PickPixel` 扫描。

跨轮次或跨 capture 回归分析时，用 investigation 保存当前 focus 和证据；事件与小纹理区域可直接做语义 diff：

```powershell
renderdoc_create_investigation(name="GI 回归", capture_ids=["<baseline_id>", "<candidate_id>"])
renderdoc_set_investigation_focus(
  investigation_id="<investigation_id>",
  capture_id="<candidate_id>",
  event_id=1250
)
renderdoc_compare_events(
  baseline_capture_id="<baseline_id>", baseline_event_id=1200,
  candidate_capture_id="<candidate_id>", candidate_event_id=1250
)
```

baseline 与 candidate 属于不同 capture session 时会并行读取；同一 capture 内仍通过该 capture 的 bridge 串行执行。

后续轮次若丢失了 investigation id，可调用 `renderdoc_list_investigations()` 恢复当前 id 和 focus。

所有相关轮次明确完成后再关闭：

```powershell
renderdoc_close_capture(capture_id="<capture_id>")
```

## 安装与运行

```powershell
uv sync --group dev
uv run renderdoc-install-extension
uv run renderdoc-mcp
```

扩展会安装到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`，默认同时写入 `UI.config` 的 `AlwaysLoad_Extensions`。若不希望修改配置，可使用 `uv run renderdoc-install-extension --no-always-load`，或设置 `$env:RENDERDOC_INSTALL_ALWAYS_LOAD = "0"`。

安装器使用跨进程锁并以完整快照替换扩展，自动排除 `__pycache__`/`.pyc`；已安装文件被修改或缺失时，下次启动会自动修复。若现有 `UI.config` 不是有效 JSON，安装器会保留原文件并给出警告。

## 环境变量

- `RENDERDOC_BACKEND`：`qrenderdoc`（默认）或 `native_python`
- `RENDERDOC_QRENDERDOC_PATH`：自定义 `qrenderdoc.exe` 路径
- `RENDERDOC_BRIDGE_TIMEOUT_SECONDS`：后端启动握手超时，默认 `30` 秒
- `RENDERDOC_CAPTURE_SESSION_IDLE_SECONDS`：capture session 空闲超时，默认 `300` 秒；设为 `0` 或负数可关闭空闲回收
- `RENDERDOC_CAPTURE_MAX_SESSIONS`：最多保留的 capture session 数，默认 `8`；优先回收最久未使用且当前空闲的 session，设为 `0` 或负数可关闭数量限制
- `RENDERDOC_NATIVE_MODULE_DIR`：`native_python` 模式下 `renderdoc.pyd` 所在目录
- `RENDERDOC_NATIVE_PYTHON_EXE`：native helper 使用的 Python，默认当前解释器
- `RENDERDOC_NATIVE_DLL_DIR`：native helper 的 DLL 目录，默认与 module 目录相同

服务端会在后台定期清理空闲 session，即使之后没有新的 MCP 请求，超时 capture 也会被关闭。

## 开发与验证

```powershell
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run mypy
uv build
```

依赖本机 RenderDoc 和可回放 `.rdc` 的测试标记为 `integration`，缺少前置条件时会跳过。Windows CI 覆盖 Python 3.10、3.12、3.14，并执行 lint、类型检查、覆盖率和打包验证。
