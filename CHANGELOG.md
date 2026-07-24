# Changelog

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
