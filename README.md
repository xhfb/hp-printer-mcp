# HP Printer MCP

MCP server for **HP Smart Tank 750** (network-connected). Exposes print, scan, copy, status, and supply-level tools for Cursor agents.

## Prerequisites

1. **Windows 10/11** host (printing uses the Windows spooler via `pywin32`).
2. Add the printer in **Settings → Bluetooth & devices → Printers & scanners** using its network IP (IPP or HP driver).
3. Python **3.10+**.
4. Printer and PC on the same LAN; note the printer IP (shown on the printer panel or router).

## Install

```powershell
cd G:\TOOL_PROJECT\hp_printer
pip install -e .
pip install pytest   # optional, for tests
```

Copy [`.env.example`](.env.example) and set at least:

```env
HP_PRINTER_HOST=192.168.x.x
HP_PRINTER_NAME=HP Smart Tank 750
HP_SCAN_OUTPUT_DIR=G:\TOOL_PROJECT\hp_printer\output
```

## Run

**STDIO (Cursor default):**

```powershell
hp-printer-mcp
```

**HTTP (local only):**

```powershell
hp-printer-mcp --http --host 127.0.0.1 --port 3002
```

## Cursor MCP configuration

Add to Cursor MCP settings (`mcp.json`):

```json
{
  "mcpServers": {
    "hp-printer": {
      "command": "hp-printer-mcp",
      "args": [],
      "env": {
        "HP_PRINTER_HOST": "192.168.x.x",
        "HP_PRINTER_NAME": "HP Smart Tank 750",
        "HP_SCAN_OUTPUT_DIR": "G:\\TOOL_PROJECT\\hp_printer\\output"
      }
    }
  }
}
```

Or with `uv`:

```json
{
  "mcpServers": {
    "hp-printer": {
      "command": "uv",
      "args": ["run", "--directory", "G:\\TOOL_PROJECT\\hp_printer", "hp-printer-mcp"],
      "env": {
        "HP_PRINTER_HOST": "192.168.x.x"
      }
    }
  }
}
```

## MCP tools

| Tool | Description |
|------|-------------|
| `discover_printer` | mDNS discovery + probe configured host |
| `get_device_status` | Host reachability, scanner state, print queue |
| `print_file` | Print PDF/image/text/Office with paper, color, duplex, quality, page range |
| `list_print_jobs` | List spooler jobs |
| `cancel_print_job` | Cancel a job by ID |
| `get_scan_capabilities` | eSCL resolutions, formats, sources |
| `get_scanner_status` | Idle/busy, ADF loaded |
| `scan_to_file` | Scan platen/ADF to PDF/JPEG/PNG (`paper`: A4, B5, … or `MAX`) |
| `get_supply_levels` | Ink levels (HP EWS → SNMP → IPP) |
| `copy_document` | Scan then print (software copy) |

All tools return JSON: `{ "success": bool, "error": string|null, "data": ... }`.

### Print settings (`print_file`)

| Parameter | Values | Notes |
|-----------|--------|-------|
| `orientation` | `portrait`, `landscape` | 方向 |
| `paper` | `A4`, `A3`, `A5`, `Letter`, `Legal`, … | 纸张大小 |
| `paper_type` | `plain`, `photo`, `cardstock`, … | 纸张类型（驱动相关） |
| `quality` | `draft`, `normal`, `high`, `best` | 输出质量 |
| `color` | `color`, `monochrome` | 彩色 / 黑白 |
| `duplex` | `none`, `long_edge`, `short_edge` | 单面 / 长边双面 / 短边双面 |
| `copies` | integer ≥ 1 | 份数 |
| `page_range` | `all` or `1-3,5` | PDF 页码范围 |

PDF/图片/文本通过 Windows DEVMODE + GDI 渲染打印；Office 格式为尽力应用驱动设置。

## Protocols

- **Print:** Windows print spooler (`win32print` / ShellExecute).
- **Scan:** [eSCL](https://mopria.org/eSCL) at `http://{IP}/eSCL/`.
- **Supplies:** HP `/DevMgmt/ConsumableConfigDyn.xml`, then SNMP Printer-MIB, then IPP.

## Security

- Default transport is **stdio** (local agent only).
- HTTP mode binds to `127.0.0.1` by default.
- File paths for print/scan are restricted to `HP_SCAN_OUTPUT_DIR`, `%USERPROFILE%\Documents`, and optional `HP_ALLOWED_PATHS`.

## Troubleshooting

| Issue | Action |
|-------|--------|
| `HP_PRINTER_HOST is not configured` | Set env var in MCP config |
| Print fails | Confirm printer name matches Windows; try printing manually once |
| Scan timeout | Check IP; try `HP_USE_HTTPS=true` if firmware requires TLS |
| ADF not loaded | Place pages in ADF; call `get_scanner_status` |
| Ink levels unknown | Smart Tank levels are estimates; check tank windows visually |
| Office formats | Install associated app (Word, etc.) or convert to PDF first |

## Tests

```powershell
pytest tests/
```

## License

MIT
