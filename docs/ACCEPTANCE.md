# Acceptance results (2026-07-24, Raspberry Pi)

Host under test: `/home/pi/hp_printer` against printer `192.168.31.11`.

| # | Case | Result |
|---|------|--------|
| 1 | Unit tests `pytest tests/` | **21 passed** |
| 2 | `print_file(content_base64=..., filename=mcp_ipp_test.txt)` | **success**, IPP `job_id=1`, format `image/jpeg`, 1 page |
| 3 | `list_print_jobs` | **success**, job `processing` then completes |
| 4 | `get_device_status` | **host_reachable=true**, eSCL Idle, IPP idle/`ready` |
| 5 | `scan_to_file(..., include_base64=True)` | **success**, PDF + `content_base64` (~191k chars) |
| 6 | `copy_document` | Skipped (scan+print already validated separately; saves paper) |
| 7 | Pi via MCP Router + base64 | Pending workstation deploy of this tree into MCP Router |

## Workstation sync

Copy or pull this tree to `G:\TOOL_PROJECT\hp_printer`, then:

```powershell
cd G:\TOOL_PROJECT\hp_printer
pip install -e .
# ensure .env has HP_HTTP_TRUST_ENV=false and HP_IPP_URI
# restart the hp-printer entry in MCP Router
```

After Router reload, Raspberry Pi Cursor can call `print_file` with `content_base64` only (no Documents staging).
