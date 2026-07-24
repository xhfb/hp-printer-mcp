from __future__ import annotations

import socket
import time
from typing import Any

from zeroconf import ServiceBrowser, Zeroconf

from hp_printer_mcp.config import Settings, fail, ok


SERVICE_TYPES = (
    "_ipp._tcp.local.",
    "_uscan._tcp.local.",
    "_escl._tcp.local.",
)


class _DiscoveryListener:
    def __init__(self) -> None:
        self.services: list[dict[str, Any]] = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if not info:
            return
        addresses = [
            socket.inet_ntoa(addr)
            for addr in info.addresses
            if len(addr) == 4
        ]
        if not addresses:
            return
        self.services.append(
            {
                "name": name.split(".")[0],
                "service_type": type_,
                "host": addresses[0],
                "port": info.port,
                "properties": {
                    k.decode() if isinstance(k, bytes) else k: (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in (info.properties or {}).items()
                },
            }
        )

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return


def _probe_host(
    host: str,
    *,
    use_https: bool,
    timeout_sec: float = 3.0,
    trust_env: bool = False,
) -> dict[str, Any]:
    import httpx

    scheme = "https" if use_https else "http"
    base = host if host.startswith("http") else f"{scheme}://{host}"
    result: dict[str, Any] = {"host": host, "reachable": False, "endpoints": {}}

    with httpx.Client(timeout=timeout_sec, verify=False, trust_env=trust_env) as client:
        for path in ("/eSCL/ScannerStatus", "/DevMgmt/ProductConfigDyn.xml"):
            url = f"{base.rstrip('/')}{path}"
            try:
                resp = client.get(url)
                result["endpoints"][path] = resp.status_code
                if resp.status_code < 500:
                    result["reachable"] = True
            except httpx.HTTPError as exc:
                result["endpoints"][path] = str(exc)

    return result


def discover_printer(settings: Settings, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    discovered: list[dict[str, Any]] = []
    zc = Zeroconf()
    listener = _DiscoveryListener()
    browsers = [
        ServiceBrowser(zc, service_type, listener) for service_type in SERVICE_TYPES
    ]
    try:
        time.sleep(timeout_sec)
    finally:
        for browser in browsers:
            browser.cancel()
        zc.close()

    seen_hosts: set[str] = set()
    for svc in listener.services:
        host = svc["host"]
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        discovered.append(svc)

    configured_probe = None
    if settings.printer_host:
        configured_probe = _probe_host(
            settings.printer_host,
            use_https=settings.use_https,
            trust_env=settings.http_trust_env,
        )

    return ok(
        {
            "mdns_services": discovered,
            "configured_host": settings.printer_host or None,
            "configured_probe": configured_probe,
        }
    )


def get_device_status(
    settings: Settings,
    *,
    scanner_status_fn,
    print_queue_count_fn,
    printer_ready_fn,
    ipp_state_fn=None,
) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    probe = _probe_host(
        settings.printer_host,
        use_https=settings.use_https,
        trust_env=settings.http_trust_env,
    )
    scanner = scanner_status_fn(settings)
    queue_count = print_queue_count_fn(settings)
    printer_ready = printer_ready_fn(settings)
    ipp_state = ipp_state_fn(settings) if ipp_state_fn else None

    data = {
        "host": settings.printer_host,
        "ipp_uri": settings.ipp_uri,
        "host_reachable": probe.get("reachable", False),
        "probe_endpoints": probe.get("endpoints", {}),
        "scanner": scanner.get("data") if scanner.get("success") else None,
        "scanner_error": scanner.get("error"),
        "printer_ready": printer_ready,
        "print_queue_job_count": queue_count,
        "ipp": ipp_state.get("data") if ipp_state and ipp_state.get("success") else None,
        "ipp_error": ipp_state.get("error") if ipp_state else None,
    }
    return ok(data)
