# Changelog

## 0.4.0 — 单作业 PWG 与能力校验

- 多页文档合成一个 `image/pwg-raster` Print-Job，双面和多份逐份生效，并只返回一个 `job_id`。
- 这台机器的 `rotated` 背面要按 PWG 5102.4 把长边背面像素转 180°。作业 7 确认长边方向正确。
- 份数写在 IPP 或页头里都只出 1 张。多份改为在光栅里按顺序重复整份；双面遇到奇数页时补一张空白背面。IPP `copies` 固定为 1，避免以后被乘两次。
- ADF 彩色扫描 8 页 PDF 已打通。扫描仪返回的 JPEG 按扫描 dpi 封装，页面是 A4，不再把像素当成点。
- 纸张、介质、质量、颜色、份数和扫描 dpi/格式按打印机或 eSCL 能力校验；不支持时直接报错。
- `media-col` 带上尺寸、边距和 `media-type`。`borderless=true` 请求四边距 0。尺寸表含 A6、4x6、5x7、Hagaki、L/2L、DL、C6、#10。`B5` 是 ISO 176×250 mm，国内常用的 182×257 mm 用 `JISB5`。
- 扫描不再接受 PNG。JPEG 扫出多页时只保存第 1 页，并在结果里警告。扫描里的 `B5` 同样是 ISO 176×250 mm。

### 真机（HP Smart Tank 750，2026-10-20）

- 长边双面、短边双面、横版、黑白、无边距、两份、JIS B5 已出纸，并用 ADF 扫描核对。
- ADF 300 dpi 彩色多页 PDF、稿台 300 dpi 扫描通过。软件复印（先扫再打）出纸 1 张。
- 墨量以 EWS 为准：彩色打印头 3YP17A、黑色打印头 X4E75A 各 20%。四个墨水瓶没有液位传感器，报告值一直是 100%。IPP `marker-levels` 全是 100%，不采用。
- 纸盒余量来自 `printer-input-tray`，当时约 24%。纸张尺寸仍是打印机里登记的 A4，放入 B5 不会自动改写。

## 0.3.0 — Agent 工具面收紧

- MCP 工具一律 `hp_` 前缀，与德佟 `detong_*` 区分；描述写明禁止打热敏标签。
- 默认只暴露 4 个：`hp_print_file`、`hp_scan_to_file`、`hp_get_status`、`hp_cancel_job`。
- 发现 / 队列列表 / 扫描能力 / 墨量 / 复印：设 `HP_MCP_EXTRA_TOOLS=1` 后注册。

## Unreleased — Network-native IPP print

### Breaking / behavioral changes
- **Print backend** switched from Windows spooler (`win32print` / GDI) to **IPP** against `HP_IPP_URI`.
- `list_print_jobs` / `cancel_print_job` now use IPP job IDs, not Windows queue IDs.
- Smart Tank printers typically reject PDF over IPP; documents are **rasterized to JPEG** before submit.

### Added
- `print_file` accepts exactly one of:
  - `file_path` (local)
  - `content_base64` + `filename` (remote clients)
  - `url` (http/https, RFC1918-only by default)
- Config: `HP_IPP_URI`, `HP_HTTP_TRUST_ENV`, `HP_MAX_UPLOAD_MB`, `HP_JOB_TMP_DIR`, `HP_ALLOW_REMOTE_URL`, `HP_URL_ALLOW_RFC1918_ONLY`, `HP_INCLUDE_SCAN_BASE64`
- `scan_to_file` can return `content_base64` for LAN clients that cannot read host paths
- HTTP clients use `trust_env=False` by default to avoid system-proxy 502 to the printer

### Compatibility
- Tool names unchanged for MCP Router / Cursor clients
- `print_win32.py` / `print_gdi.py` remain in tree but are no longer wired into `server.py`
- Package runs on Linux and Windows (no pywin32 required for print path)
