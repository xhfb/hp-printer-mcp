from __future__ import annotations

import base64
import ipaddress
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from hp_printer_mcp.config import Settings
from hp_printer_mcp.http_util import make_client

PRINTABLE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".log",
    ".md",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}


class JobInputError(ValueError):
    pass


def job_tmp_root(settings: Settings) -> Path:
    root = settings.job_tmp_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def cleanup_old_jobs(settings: Settings) -> int:
    """Delete job temp dirs older than TTL. Returns number removed."""
    root = job_tmp_root(settings)
    removed = 0
    cutoff = time.time() - settings.job_tmp_ttl_sec
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _ensure_size(path: Path, max_bytes: int) -> None:
    size = path.stat().st_size
    if size > max_bytes:
        path.unlink(missing_ok=True)
        raise JobInputError(
            f"File exceeds max size ({size} bytes > {max_bytes} bytes)"
        )


def _is_rfc1918(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # hostname: allow if RFC1918-only is disabled; when enabled, resolve check skipped
        # for simplicity require IP when RFC1918-only is on
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
    )


def _download_url(settings: Settings, url: str, dest: Path) -> Path:
    if not settings.allow_remote_url:
        raise JobInputError("Remote URL download is disabled (HP_ALLOW_REMOTE_URL=false)")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise JobInputError("Only http/https URLs are allowed")
    if parsed.username or parsed.password:
        raise JobInputError("URLs with embedded credentials are not allowed")

    host = parsed.hostname or ""
    if settings.url_allow_rfc1918_only:
        if not _is_rfc1918(host):
            raise JobInputError(
                f"URL host '{host}' is not a private/RFC1918 address "
                "(set HP_URL_ALLOW_RFC1918_ONLY=false to allow)"
            )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0)
    with make_client(settings, timeout=timeout) as client:
        with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.is_redirect:
                raise JobInputError("URL redirects are not followed")
            resp.raise_for_status()
            written = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise JobInputError(
                            f"Download exceeds max size ({settings.max_upload_mb}MB)"
                        )
                    fh.write(chunk)
    return dest


def resolve_print_input(
    settings: Settings,
    *,
    file_path: str | None = None,
    content_base64: str | None = None,
    filename: str | None = None,
    url: str | None = None,
) -> tuple[Path, Path]:
    """
    Resolve one of file_path / content_base64 / url into a local file.

    Returns (source_path, job_dir). Caller may delete job_dir when done.
    """
    provided = [bool(file_path), bool(content_base64), bool(url)]
    if sum(provided) != 1:
        raise JobInputError(
            "Provide exactly one of: file_path, content_base64 (+filename), or url"
        )

    cleanup_old_jobs(settings)
    job_dir = job_tmp_root(settings) / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    try:
        if file_path:
            # Allow any readable local path within size limit (LAN MCP may stage files).
            # Still prefer allowed dirs when configured, but do not hard-block temp/uploads.
            resolved = Path(file_path).expanduser().resolve()
            if not resolved.is_file():
                raise JobInputError(f"File not found: {resolved}")
            _ensure_size(resolved, max_bytes)
            suffix = resolved.suffix.lower()
            if suffix not in PRINTABLE_EXTENSIONS:
                raise JobInputError(
                    f"Unsupported file type '{suffix}'. "
                    f"Supported: {', '.join(sorted(PRINTABLE_EXTENSIONS))}"
                )
            # Copy into job dir so cleanup is uniform
            dest = job_dir / resolved.name
            shutil.copy2(resolved, dest)
            return dest, job_dir

        if content_base64:
            if not filename or not filename.strip():
                raise JobInputError("filename is required with content_base64")
            name = Path(filename.strip()).name
            suffix = Path(name).suffix.lower()
            if suffix not in PRINTABLE_EXTENSIONS:
                raise JobInputError(
                    f"Unsupported file type '{suffix}'. "
                    f"Supported: {', '.join(sorted(PRINTABLE_EXTENSIONS))}"
                )
            try:
                raw = base64.b64decode(content_base64, validate=False)
            except Exception as exc:
                raise JobInputError(f"Invalid content_base64: {exc}") from exc
            if len(raw) > max_bytes:
                raise JobInputError(
                    f"content_base64 exceeds max size ({settings.max_upload_mb}MB)"
                )
            dest = job_dir / name
            dest.write_bytes(raw)
            return dest, job_dir

        # url
        assert url is not None
        name = Path(urlparse(url).path).name or "download.bin"
        if "." not in name:
            name = f"{name}.bin"
        dest = job_dir / Path(name).name
        _download_url(settings, url, dest)
        suffix = dest.suffix.lower()
        if suffix not in PRINTABLE_EXTENSIONS:
            raise JobInputError(
                f"Unsupported downloaded file type '{suffix}'. "
                f"Supported: {', '.join(sorted(PRINTABLE_EXTENSIONS))}"
            )
        _ensure_size(dest, max_bytes)
        return dest, job_dir
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
