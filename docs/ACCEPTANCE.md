# Acceptance results

## 2026-10-20, workstation against HP Smart Tank 750 (`192.168.31.11`)

Firmware seen earlier the same day: SAYAADPP1N002.2630B.00.

| Case | Result |
|------|--------|
| One `image/pwg-raster` job for multi-page print | Pass. Long-edge duplex direction confirmed on paper |
| Short-edge duplex, landscape, monochrome, borderless, collated copies | Pass. Copies ejected two identical sheets |
| JIS B5 (`JISB5`, 182×257 mm), plain, color, simplex | Pass. ADF scan showed the 3 mm frame and four corner blocks |
| ADF scan, 300 dpi, RGB24, multi-page PDF | Pass. Page size is A4 at the scan dpi |
| Platen scan, 300 dpi, RGB24 | Pass |
| Software copy (platen scan, then one print) | Pass, 1 sheet |
| Supplies | EWS: printheads CMY `3YP17A` and K `X4E75A` at 20%. Tanks C/M/Y/K report 100% and are not sensed. IPP marker levels stay at 100% and are not used |
| Input tray | `printer-input-tray` level about 24%. `media-ready` stayed `iso_a4_210x297mm` after B5 was loaded |

Photo paper, envelopes, 600 dpi raster, grayscale/black-and-white scan, and a full remote copy from the ADF were not printed in this round.

## 2026-07-24, Raspberry Pi

Host under test: `/home/pi/hp_printer` against printer `192.168.31.11`.

| # | Case | Result |
|---|------|--------|
| 1 | Unit tests `pytest tests/` | **21 passed** |
| 2 | `hp_print_file(content_base64=..., filename=mcp_ipp_test.txt)` | **success**, IPP `job_id=1`, format `image/jpeg`, 1 page |
| 3 | `list_print_jobs`（现为 extra `hp_list_jobs`） | **success**, job `processing` then completes |
| 4 | `hp_get_status` | **host_reachable=true**, eSCL Idle, IPP idle/`ready` |
| 5 | `hp_scan_to_file(..., include_base64=True)` | **success**, PDF + `content_base64` (~191k chars) |
| 6 | `copy_document`（现为 extra `hp_copy_document`） | Skipped (scan+print already validated separately; saves paper) |
| 7 | Pi via MCP Router + base64 | Pending workstation deploy of this tree into MCP Router |

## Workstation sync

Copy or pull this tree to `G:\TOOL_PROJECT\hp_printer`, then:

```powershell
cd G:\TOOL_PROJECT\hp_printer
pip install -e .
# ensure .env has HP_HTTP_TRUST_ENV=false and HP_IPP_URI
# restart the hp-printer entry in MCP Router
```

After Router reload, Raspberry Pi Cursor can call `hp_print_file` with `content_base64` only (no Documents staging).
