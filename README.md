# HP Printer MCP

MCP server for **HP Smart Tank 750** (network-connected). Exposes print, scan, copy, status, and supply-level tools for Cursor agents.

## Protocols (network-native)

| Feature | Protocol |
|---------|----------|
| Print | **IPP** (`ipp://{host}:631/ipp/print`) — documents rasterized to JPEG when PDF is unsupported |
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

| Tool | Description |
|------|-------------|
| `discover_printer` | mDNS discovery + probe configured host |
| `get_device_status` | Host reachability, eSCL scanner, IPP printer-state |
| `print_file` | Print via IPP — `file_path` **or** `content_base64`+`filename` **or** `url` |
| `list_print_jobs` | List IPP jobs |
| `cancel_print_job` | Cancel by IPP `job_id` |
| `get_scan_capabilities` | eSCL resolutions, formats, sources |
| `get_scanner_status` | Idle/busy, ADF loaded |
| `scan_to_file` | Scan to PDF/JPEG/PNG; optional `content_base64` in response |
| `get_supply_levels` | Ink levels (best effort) |
| `copy_document` | Scan then IPP-print |

All tools return JSON: `{ "success": bool, "error": string|null, "data": ... }`.

### Print settings (`print_file`)

| Parameter | Values | Notes |
|-----------|--------|-------|
| `file_path` / `content_base64`+`filename` / `url` | one required | remote clients should use base64 |
| `orientation` | `portrait`, `landscape` | |
| `paper` | `A4`, `A3`, `A5`, `Letter`, … | mapped to IPP `media` |
| `paper_type` | `plain`, `photo`, … | may be ignored over IPP (warning returned) |
| `quality` | `draft`, `normal`, `high`, `best` | IPP print-quality |
| `color` | `color`, `monochrome` | |
| `duplex` | `none`, `long_edge`, `short_edge` | |
| `copies` | integer ≥ 1 | |
| `page_range` | `all` or `1-3,5` | PDF only |

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
| Blank / wrong size | Check `paper` + `orientation`; Smart Tank receives JPEG pages |

## Tests

```bash
pytest tests/
```

## License

MIT
