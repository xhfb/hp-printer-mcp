# HP Smart Tank 750 — hp-printer MCP capability review

Status after the same day: items 2, 3, and 4 below are implemented in 0.4.0 and checked on this printer (duplex, copies, borderless, JIS B5, ADF and platen scan, software copy). Sections 2 and 3 describe the code as it was when this review was written. Supplies and tray level were read live: EWS printheads at 20%, tanks report 100% because they are not sensed, tray level about 24%. Items 1 and 5–11 are still open.

Date: 2026-10-20. Device: HP Smart Tank 750 series, firmware SAYAADPP1N002.2630B.00, S/N TH62N9B2Z8.
How it was reached: the PC mini bridge (IPP at 100.80.207.121:9163, HTTP at :9180). Only read-only queries were sent: Get-Printer-Attributes, eSCL GETs and LEDM GETs. Nothing was printed, scanned or copied.
Raw dumps are in `capabilities/`. They include `ipp_get_printer_attributes.txt`, `eSCL_ScannerCapabilities`, `eSCL_ScannerStatus` and `DevMgmt_*.xml`.

## 1. What the device actually supports

| Area | Device capability |
|---|---|
| Print PDLs | `application/vnd.hp-PCL`, `image/jpeg`, `image/urf`, `image/pwg-raster`, `application/PCLm`. **No `application/pdf`**. |
| Operations | Print-Job, Validate-Job, Create-Job, Send-Document, Cancel-Job, Cancel-My-Jobs, Get-Job-Attributes, Get-Jobs, Print-URI, Identify-Printer |
| Media sizes | Letter, Legal, Executive, 8x10, Statement, A4, A5, A6, B5 (ISO/JIS), Hagaki, Oufuku, 4x6, 10x15cm, 5x7, 5x8, 3.5x5 (L), 2L, #10 env, DL, C6, Chou3/4, Foolscap, custom 3.5x5 to 8.5x14 in. **No A3/B4/Tabloid.** |
| Borderless | Yes: margins 0 or 296 (media-col-ready has a 0-margin A4 entry; LEDM BorderlessPrinting=true) |
| Media types | stationery, stationery-lightweight, photographic-glossy, com.hp-photographic-inkjet, specialty-glossy(-inkjet), matte-presentation/brochure/inkjet |
| Trays | 1 input tray, `main` (Tray 1, 100 sheets, currently about 24% full, A4 plain loaded); output face-up |
| Duplex | Auto duplexer: `sides` = one-sided, two-sided-long-edge, two-sided-short-edge (LEDM DuplexSheets=262) |
| Color modes | auto, auto-monochrome, monochrome, color |
| Quality | draft, normal, high; resolution 300/600/1200 dpi |
| Copies | 1–99, collated and uncollated (multiple-document-handling) |
| Page ranges | page-ranges-supported = true |
| Orientation | orientation-requested-supported = **portrait only** |
| Scaling | print-scaling: auto, auto-fit, fill, fit, none |
| Content optimize | auto, photo, graphics, text, text-and-graphics |
| Finishings | none |
| Supplies | IPP marker-levels for C/M/Y/K report 100 (not meaningful for tanks). LEDM reports printheads CMY (3YP17A) = 20% and K (X4E75A) = 20%, plus tanks C/M/Y/K at 100% (tanks are not sensed) |
| Counters (LEDM) | 968 impressions in total (475 mono, 493 color), 437 simplex and 262 duplex sheets, 6 jams, 10 mispicks, 191 scans (168 ADF, 21 flatbed) |
| Scan sources | Platen: 75–1200 dpi, up to 2550x3508 (A4). ADF: **simplex only**, 35 sheets, 75–300 dpi, height up to 4200 (14 in). No AdfDuplex. |
| Scan colors/formats | BlackAndWhite1, Grayscale8, RGB24; application/pdf, image/jpeg. **No PNG.** Intents: Document, Photo, TextAndGraphic, Preview |
| Scanner status | State=Idle; AdfState=ScannerAdfEmpty |
| Copy | Copying works from the front panel (CopyApplicationSubunit). Remote network copy is not exposed (no CopyConfig LEDM). Software copy has to be scan + print. |
| Status | IPP printer-state/reasons; LEDM ProductStatusDyn (e.g. inPowerSave) |

## 2. The MCP as it is today

The default tools are:

- `hp_print_file(file_path|content_base64+filename|url, copies, orientation, paper, paper_type, quality, color, duplex, page_range, printer_name)`
- `hp_scan_to_file(source, dpi, format, color_mode, paper, orientation, output_path, include_base64)`
- `hp_get_status()`
- `hp_cancel_job(job_id, printer_name)`

These tools only appear with `HP_MCP_EXTRA_TOOLS=1`:

- `hp_discover_printer(timeout_sec)`
- `hp_list_jobs(printer_name)`
- `hp_get_scan_capabilities()`
- `hp_get_scanner_status()`
- `hp_get_supply_levels()`
- `hp_copy_document(source, copies, orientation, paper, paper_type, quality, color, duplex, dpi, format)`

## 3. Gap table

| Capability | In MCP? | Notes |
|---|---|---|
| Print PDF/image/text | Yes | Every input is rasterized to JPEG, because the device has no PDF PDL |
| Multi-page as **one** job | **No** | One IPP job is sent per page (`#p1`, `#p2`…), so `job_id` comes back null for multi-page jobs |
| Duplex | **Broken** | `sides` is sent, but every job holds a single page, so nothing is ever printed on the back. Fix: send PWG-raster/PCLm/URF multi-page in one job |
| Copies | Partial | Sent on each per-page job, so the output comes out uncollated (1,1,2,2). Collated copies are impossible today |
| Page ranges | Yes (client-side) | Done during rasterization, which is fine |
| Paper sizes | Partial / wrong | It accepts A3/B4/Tabloid/Legal-style Windows DMPAPER names the device doesn't support. MEDIA_MAP has no entries for A6, 4x6, 5x7, Hagaki, envelopes (DL/C6/#10) or L/2L, and for unmapped sizes `media` is silently omitted |
| Media type (photo etc.) | **No** | `paper_type` is validated and then ignored with a warning; it never maps to `media-type`/`media-col` |
| Borderless | **No** | Needs `media-col` with zero margins |
| Color mode | Partial | color/monochrome only; auto and auto-monochrome are missing |
| Quality | Yes | `best` maps to high (5), which is fine. Resolution (1200 dpi) is not exposed |
| Orientation | Partial | Device only advertises portrait. Landscape works through rasterizer rotation, but `orientation-requested=4` may be ignored or rejected |
| Scaling / fit | No (client fixed fit) | print-scaling is not exposed |
| Content optimize (photo/text) | No | |
| Tray selection | N/A | Only one tray exists |
| Job list | Extra only | `pages` is always None; it uses time-at-creation only |
| Job cancel | Yes | |
| Identify-Printer | No | Could be a cheap "beep/flash" test |
| Ink/printhead levels | Extra only, partial | Through the bridge, EWS returns **403 unless `Host: 192.168.31.11`** is sent. It then falls back to SNMP (not bridged), then IPP marker-levels (always 100). When EWS does work, the parser mislabels printhead % as ink. Tank levels aren't sensed |
| Usage counters | No | ProductUsageDyn has rich data |
| Status details | Partial | IPP state plus eSCL only. Missing: tray paper level, media-ready, power-save, printer-state-message, LEDM alerts |
| Scan Platen | Yes | |
| Scan ADF | Yes | ADF-empty detection works (`ScannerAdfEmpty` is read as empty) |
| ADF multi-page to PDF | Yes for PDF | It merges pages. For **jpeg it silently returns only page 1** |
| ADF duplex scan | N/A | Device is simplex ADF |
| Scan dpi validation | No | The ADF caps at 300 dpi, but 600 is accepted and fails at the device |
| Scan formats | Partial / wrong | It offers PNG, which the device doesn't support (the job would fail) |
| Scan color | Yes (raw eSCL names) | BlackAndWhite1 is not documented |
| Scan intent | Hardcoded | `ContentType=TextAndPhoto`; eSCL 2.63 Intent is not used |
| Copy | Extra only | Software scan+print, so it inherits the duplex, collation and media bugs above |

## 4. Other issues and dead code

- **Stale `.env`**: it points to the old bridge `100.65.16.105`. The bridge is now at `100.80.207.121`.
- **Host header**: when the MCP goes through the bridge, all LEDM (`/DevMgmt/*`) requests get 403 because the Host header is the bridge address. eSCL works either way. Fix: add an `HP_PRINTER_HTTP_HOST_HEADER` setting, or a subnet route.
- The `printer-uri-supported` the device returns mixes `ipp://100.80.207.121/...` (port stripped). That's harmless, but don't follow it.
- Windows legacy code: `print_win32.py`, `print_gdi.py` and DEVMODE parts of `print_options.py` (`PAPER_SIZES` DMPAPER ids, `apply_settings_to_devmode`, `get_printer_devmode`) are not imported by the server, which makes them dead code. `PAPER_SIZES` still drives validation and the rasterizer, which is the source of the wrong size list. Other leftovers are `scripts/*.ps1` and `hourly_print.py`. Root clutter: `url_test.jpg`, `case1_b64.txt`, `gen_boundary_stress_v2.py`, `verify_boundary_v2.py`.
- `printer_name` params are accepted and then ignored.
- `_choose_document_format` prefers JPEG and never uses pwg-raster/urf/PCLm, even though `_printer_formats` requests sides-supported.
- `print_queue_count` swallows errors and returns 0.
- Supplies: the SNMP path is unusable across the bridge (UDP), and the IPP path reports cartridges at 100% for a tank printer. Both are misleading without labels.
- Scan JPEG/PNG multi-page: only `pages[0]` is written, and there's no warning.

## 5. Recommended improvements (prioritized)

| # | Improvement | Why | Effort |
|---|---|---|---|
| 1 | Fix `.env` bridge IP, and add a Host-header override for LEDM | Supplies, status and counters work through the bridge | 0.5 h |
| 2 | **Single-job multi-page print** via PWG-raster (or URF/PCLm) encoder in one Print-Job (or Create-Job + Send-Document) | Makes duplex actually work, gives collated copies and one job_id | 1–1.5 d (PWG raster encoder in Python is about 150 lines: header + PackBits) |
| 3 | Drive capabilities from the device: validate paper, media-type, quality, color, dpi and format against Get-Printer-Attributes / eSCL caps, and drop the DMPAPER table | Clear errors instead of silent ignores | 0.5 d |
| 4 | `media-col` support: media-type (plain/photo-glossy/matte…), borderless (0 margins), full size map (A6, 4x6, 5x7, Hagaki, L/2L, DL/C6/#10 envelopes) | Photo printing | 0.5–1 d (depends on #2 for raster at the right size) |
| 5 | Make supplies a default tool or fold it into `hp_get_status`: printhead % plus "tanks not sensed" note, tray paper level (printer-input-tray), media-ready, power-save, state-message | Ink and paper at a glance | 0.5 d |
| 6 | Scan fixes: per-source dpi validation (ADF ≤300), remove PNG (or convert locally), multi-page JPEG → zip or per-page files, Intent param, document BlackAndWhite1, `pages` returned list | ADF batches that don't fail | 0.5 d |
| 7 | Promote `hp_list_jobs` to default with Get-Job-Attributes (pages, state-reasons); add `hp_identify` (Identify-Printer) | Visibility | 2–3 h |
| 8 | Expose print-color-mode auto, print-scaling (fit/fill/none), print-content-optimize, printer-resolution | Fine control | 2–3 h (after #2) |
| 9 | Usage counters tool (ProductUsageDyn) | Nice-to-have | 2 h |
| 10 | Remove the Win32/GDI dead code, scripts and root clutter; update README/tests | Maintainability | 2–3 h |
| 11 | Copy: after #2, pass collated copies + duplex; ADF→multi-page→one job | Real "copy 10 pages double-sided" | 1–2 h after #2 |
