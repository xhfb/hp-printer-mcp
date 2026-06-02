from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.copy import copy_document as run_copy_document
from hp_printer_mcp.discovery import discover_printer as run_discover_printer
from hp_printer_mcp.discovery import get_device_status as run_get_device_status
from hp_printer_mcp.print_win32 import cancel_print_job as run_cancel_print_job
from hp_printer_mcp.print_win32 import is_printer_ready
from hp_printer_mcp.print_win32 import list_print_jobs as run_list_print_jobs
from hp_printer_mcp.print_win32 import print_file as run_print_file
from hp_printer_mcp.print_win32 import print_queue_count
from hp_printer_mcp.scan_escl import get_scan_capabilities as run_get_scan_capabilities
from hp_printer_mcp.scan_escl import get_scanner_status as run_get_scanner_status
from hp_printer_mcp.scan_escl import scan_to_file as run_scan_to_file
from hp_printer_mcp.supplies import get_supply_levels as run_get_supply_levels

mcp = FastMCP("hp-printer")


@mcp.tool()
async def discover_printer(timeout_sec: float = 5.0) -> dict:
    """Discover HP/network printers via mDNS and probe the configured HP_PRINTER_HOST."""
    settings = load_settings()
    return run_discover_printer(settings, timeout_sec=timeout_sec)


@mcp.tool()
async def get_device_status() -> dict:
    """Get aggregated printer/scanner status for the configured HP Smart Tank 750."""
    settings = load_settings()
    return run_get_device_status(
        settings,
        scanner_status_fn=run_get_scanner_status,
        print_queue_count_fn=print_queue_count,
        printer_ready_fn=lambda s: is_printer_ready(s),
    )


@mcp.tool()
async def print_file(
    file_path: str,
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    page_range: str = "all",
    printer_name: Optional[str] = None,
) -> dict:
    """Print a local document via the Windows print queue with full driver settings.

    orientation: portrait | landscape
    paper: A4, A3, A5, Letter, Legal, B5, ...
    paper_type: plain | photo | cardstock | envelope | labels | transparency
    quality: draft | normal | high | best
    color: color | monochrome
    duplex: none | long_edge (沿长边) | short_edge (沿短边)
    page_range: all | e.g. 1-3,5 (PDF only)
    """
    settings = load_settings()
    return run_print_file(
        settings,
        file_path=file_path,
        copies=copies,
        orientation=orientation,
        paper=paper,
        paper_type=paper_type,
        quality=quality,
        color=color,
        duplex=duplex,
        page_range=page_range,
        printer_name=printer_name,
    )


@mcp.tool()
async def list_print_jobs(printer_name: Optional[str] = None) -> dict:
    """List current print jobs on the configured Windows printer queue."""
    settings = load_settings()
    return run_list_print_jobs(settings, printer_name=printer_name)


@mcp.tool()
async def cancel_print_job(job_id: int, printer_name: Optional[str] = None) -> dict:
    """Cancel a print job by job ID on the Windows print queue."""
    settings = load_settings()
    return run_cancel_print_job(settings, job_id=job_id, printer_name=printer_name)


@mcp.tool()
async def get_scan_capabilities() -> dict:
    """Return eSCL scanner capabilities (resolutions, formats, ADF/platen sources)."""
    settings = load_settings()
    return run_get_scan_capabilities(settings)


@mcp.tool()
async def get_scanner_status() -> dict:
    """Return eSCL scanner status including idle/busy state and ADF load state."""
    settings = load_settings()
    return run_get_scanner_status(settings)


@mcp.tool()
async def scan_to_file(
    source: str = "Platen",
    dpi: int = 300,
    format: str = "pdf",
    color_mode: str = "RGB24",
    paper: str = "A4",
    orientation: str = "portrait",
    output_path: Optional[str] = None,
) -> dict:
    """Scan from platen or ADF and save to a local file (pdf/jpeg/png).

    paper: A4, A5, B5, Letter, ... or MAX for full scan area.
    orientation: portrait | landscape
    """
    settings = load_settings()
    return run_scan_to_file(
        settings,
        source=source,
        dpi=dpi,
        format=format,
        color_mode=color_mode,
        paper=paper,
        orientation=orientation,
        output_path=output_path,
    )


@mcp.tool()
async def get_supply_levels() -> dict:
    """Read ink/supply levels via HP EWS, SNMP, or IPP (best effort)."""
    settings = load_settings()
    return run_get_supply_levels(settings)


@mcp.tool()
async def copy_document(
    source: str = "Platen",
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    dpi: int = 300,
    format: str = "pdf",
) -> dict:
    """Copy by scanning then printing (software workflow)."""
    settings = load_settings()
    return run_copy_document(
        settings,
        source=source,
        copies=copies,
        orientation=orientation,
        paper=paper,
        paper_type=paper_type,
        quality=quality,
        color=color,
        duplex=duplex,
        dpi=dpi,
        format=format,
    )
