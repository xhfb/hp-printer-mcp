from __future__ import annotations

import httpx

from hp_printer_mcp.config import Settings


def make_client(
    settings: Settings,
    *,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Client:
    """HTTP client that never uses system proxy env (avoids LAN 502 via bad proxies)."""
    if timeout is None:
        read_timeout = max(settings.escl_timeout_sec, settings.scan_poll_max_sec)
        timeout = httpx.Timeout(connect=30.0, read=read_timeout, write=30.0, pool=30.0)
    return httpx.Client(
        timeout=timeout,
        verify=False,
        trust_env=settings.http_trust_env,
    )
