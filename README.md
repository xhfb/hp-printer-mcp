# HP Printer MCP

MCP server for an **HP Smart Tank 750** on the local network. Default tools print, preview, scan, report status, and cancel jobs. Discover, job list, scan capabilities, supplies, and copy stay unregistered until `HP_MCP_EXTRA_TOOLS=1`.

Every tool name starts with `hp_` and controls this HP printer over IPP and eSCL.

## Protocols (network-native)

| Feature | Protocol |
|---------|----------|
| Print | **IPP** (`ipp://{host}:631/ipp/print`) — multi-page documents become one `image/pwg-raster` job (duplex and collated copies). JPEG is only a per-page fallback |
| Scan | **eSCL** (`http://{host}/eSCL/`) |
| Supplies | HP EWS → SNMP → IPP (best effort) |

Windows spooler is **no longer required**. The same MCP can run on Windows or Linux (e.g. Raspberry Pi) as long as it can reach the printer on the LAN.

## Prerequisites

1. Printer on the LAN with a stable IP (panel / router DHCP reservation).
2. Python **3.10+**.
3. Optional: place the host behind [MCP Router](https://github.com/mcp-router/mcp-router) so other LAN machines (Cursor) can call tools with a token.

## Install

```powershell
cd G:\TOOL_PROJECT\hp_printer   # or /home/pi/hp_printer
pip install -e .
pip install pytest              # optional
```

Copy [`.env.example`](.env.example):

```env
HP_PRINTER_HOST=192.168.31.11
HP_PRINTER_NAME=HP Smart Tank 750
HP_IPP_URI=ipp://192.168.31.11:631/ipp/print
HP_SCAN_OUTPUT_DIR=./output
HP_HTTP_TRUST_ENV=false
# HP_MCP_EXTRA_TOOLS=1
```

## Run

**STDIO (Cursor / MCP Router default):**

```bash
hp-printer-mcp
```

**HTTP (local only by default):**

```bash
hp-printer-mcp --http --host 127.0.0.1 --port 3002
```

## Cursor / MCP Router

Workstation still registers this server in MCP Router. LAN clients (e.g. Raspberry Pi) keep pointing at the router:

```json
{
  "mcpServers": {
    "mcp-router": {
      "url": "http://192.168.31.26:3282/mcp",
      "headers": {
        "Authorization": "Bearer mcpr_..."
      }
    }
  }
}
```

### Remote print (no host-local file)

```json
{
  "content_base64": "<base64 of file bytes>",
  "filename": "test.txt",
  "paper": "A4",
  "color": "monochrome"
}
```

## MCP tools

Five tools are registered by default:

| Tool | Description |
|------|-------------|
| `hp_print_file` | IPP 打 PDF/图/文本；成功返回 `job_id` |
| `hp_preview_print` | 同一套参数的打印预览，不出纸；返回阅读方向图片 |
| `hp_scan_to_file` | eSCL 扫描到 PDF/JPEG（不支持 PNG） |
| `hp_get_status` | 主机 / IPP / 扫描头状态 |
| `hp_cancel_job` | 按 IPP `job_id` 取消 |

设 `HP_MCP_EXTRA_TOOLS=1` 才注册：`hp_discover_printer`、`hp_list_jobs`、`hp_get_scan_capabilities`、`hp_get_scanner_status`、`hp_get_supply_levels`、`hp_copy_document`。

All tools return JSON: `{ "success": bool, "error": string|null, "data": ... }`.

### Print settings (`hp_print_file`)

| Parameter | Values | Notes |
|-----------|--------|-------|
| `file_path` / `content_base64`+`filename` / `url` | one required | remote clients should use base64 |
| `orientation` | `portrait`, `landscape` | landscape is composed wide, then rotated into the portrait feed |
| `paper` | `A4`, `A5`, `A6`, `Letter`, `Legal`, `4x6`, `Hagaki`, `L`, `2L`, `DL`, `C6`, `#10`, `JISB5`, … | checked against the printer `media-supported` list. No A3. `B5` is ISO 176×250 mm; office B5 in China is `JISB5` (182×257 mm) |
| `paper_type` | `plain`, `lightweight`, `photo`, `matte`, `brochure`, … | sent as IPP `media-type` inside `media-col` |
| `borderless` | `true` / `false` | `true` asks for 0 mm margins when that size and type allow it |
| `quality` | `draft`, `normal`, `high`, `best` | IPP print-quality. Raster stays 300 dpi when the printer offers it |
| `color` | `color`, `monochrome`, `auto`, `auto-monochrome` | checked against `print-color-mode-supported` |
| `duplex` | `none`, `long_edge`, `short_edge` | one PWG job, so the back side is actually printed |
| `copies` | integer ≥ 1, within `copies-supported` | collated by repeating the page sequence inside the one PWG document. IPP `copies` stays 1 so this printer does not drop or double them |
| `page_range` | `all` or `1-3,5` | PDF only |

`hp_preview_print` takes the same arguments, plus `max_pages` (default 6, cap 8) and `show_margins`. It does not contact the printer. The tool result is JSON followed by one image per previewed page. The pale red band and dashed line mark this machine's 2.96 mm unprintable margin and are not printed. Landscape is shown in reading orientation; the real job still rotates that page into the portrait feed. Files land in `{HP_SCAN_OUTPUT_DIR}/preview/`.

## Security

- Default transport is **stdio** (local agent / MCP Router child process).
- HTTP mode binds to `127.0.0.1` by default.
- Uploads capped by `HP_MAX_UPLOAD_MB` (default 25).
- URL fetch: http/https only, no redirects, RFC1918-only by default (`HP_URL_ALLOW_RFC1918_ONLY`).
- `HP_HTTP_TRUST_ENV=false` avoids system HTTP proxies breaking LAN printer access (common cause of 502).

## Troubleshooting

| Issue | Action |
|-------|--------|
| `HP_PRINTER_HOST is not configured` | Set env / `.env` |
| IPP 401 | Check `HP_IPP_USERNAME` / `HP_IPP_PASSWORD` (guest often works) |
| Scan 502 on Windows only | Ensure `HP_HTTP_TRUST_ENV=false`; clear HTTP_PROXY for that host |
| Office `.docx` print fails | Convert to PDF/TXT first (IPP path rasterizes PDF/images/text) |
| Blank / wrong size | Check `paper` + `orientation`. Pages are one PWG raster sized to the media keyword |
| Scan rejected | dpi, format, and paper are checked per source. ADF tops out at 300 dpi; PNG is not a scanner format. Scan `B5` is ISO 176×250 mm |
| JPEG scan keeps one page | Use `format=pdf` when the feeder returns more than one page |

## Tests

```bash
pytest tests/
```

## License

MIT
