from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hp_printer_mcp.config import Settings, fail, ok
from hp_printer_mcp.print_gdi import print_with_gdi
from hp_printer_mcp.print_options import PrintSettings, normalize_print_settings

PRINTABLE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}

GDI_EXTENSIONS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _win32():
    if sys.platform != "win32":
        raise RuntimeError("Printing is only supported on Windows")
    try:
        import win32api
        import win32con
        import win32print
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required for printing on Windows. Install with: pip install pywin32"
        ) from exc
    return win32api, win32con, win32print


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Printing is only supported on Windows")


def _resolve_printer_name(settings: Settings, printer_name: str | None) -> str:
    _require_windows()
    _, _, win32print = _win32()
    if printer_name:
        return printer_name
    if settings.printer_name:
        return settings.printer_name
    return win32print.GetDefaultPrinter()


def list_installed_printers() -> list[str]:
    _require_windows()
    _, _, win32print = _win32()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags)
    return [entry[2] for entry in printers]


def is_printer_ready(settings: Settings, printer_name: str | None = None) -> bool:
    try:
        _, _, win32print = _win32()
        name = _resolve_printer_name(settings, printer_name)
        handle = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(handle, 2)
            status = info.get("Status", 0)
            attributes = info.get("Attributes", 0)
            offline = bool(status & win32print.PRINTER_STATUS_OFFLINE)
            paused = bool(status & win32print.PRINTER_STATUS_PAUSED)
            work_offline = bool(attributes & win32print.PRINTER_ATTRIBUTE_WORK_OFFLINE)
            return not (offline or paused or work_offline)
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        return False


def list_print_jobs(settings: Settings, *, printer_name: str | None = None) -> dict[str, Any]:
    _require_windows()
    try:
        _, _, win32print = _win32()
        name = _resolve_printer_name(settings, printer_name)
        handle = win32print.OpenPrinter(name)
        try:
            jobs = win32print.EnumJobs(handle, 0, 999, 1)
            data = [
                {
                    "job_id": job["JobId"],
                    "document": job.get("pDocument"),
                    "status": job.get("Status"),
                    "pages": job.get("TotalPages"),
                    "submitted": str(job.get("Submitted")),
                    "username": job.get("pUserName"),
                }
                for job in jobs
            ]
            return ok({"printer_name": name, "jobs": data})
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return fail(f"Failed to list print jobs: {exc}")


def cancel_print_job(
    settings: Settings,
    *,
    job_id: int,
    printer_name: str | None = None,
) -> dict[str, Any]:
    _require_windows()
    try:
        _, _, win32print = _win32()
        name = _resolve_printer_name(settings, printer_name)
        handle = win32print.OpenPrinter(name)
        try:
            win32print.SetJob(handle, job_id, 0, None, win32print.JOB_CONTROL_DELETE)
            return ok({"printer_name": name, "job_id": job_id, "cancelled": True})
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return fail(f"Failed to cancel print job: {exc}")


def print_queue_count(settings: Settings, *, printer_name: str | None = None) -> int:
    result = list_print_jobs(settings, printer_name=printer_name)
    if not result.get("success"):
        return 0
    return len(result["data"]["jobs"])


def _print_office_with_devmode(
    path: Path,
    printer_name: str,
    settings: PrintSettings,
) -> None:
    """Best-effort Office print: temporarily apply DEVMODE then ShellExecute."""
    from hp_printer_mcp.print_options import get_printer_devmode

    win32api, win32con, win32print = _win32()
    handle = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(handle, 2)
        original_devmode = info["pDevMode"]
        info["pDevMode"] = get_printer_devmode(printer_name, settings)
        win32print.SetPrinter(handle, 2, info, 0)
        try:
            for _ in range(settings.copies):
                win32api.ShellExecute(
                    0,
                    "print",
                    str(path),
                    f'/d:"{printer_name}"',
                    str(path.parent),
                    win32con.SW_HIDE,
                )
        finally:
            restore = dict(info)
            restore["pDevMode"] = original_devmode
            win32print.SetPrinter(handle, 2, restore, 0)
    finally:
        win32print.ClosePrinter(handle)


def print_file(
    settings: Settings,
    *,
    file_path: str,
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    page_range: str = "all",
    printer_name: str | None = None,
) -> dict[str, Any]:
    _require_windows()
    try:
        resolved = settings.ensure_allowed_path(file_path, for_write=False)
    except PermissionError as exc:
        return fail(str(exc))

    if not resolved.exists():
        return fail(f"File not found: {resolved}")

    if resolved.suffix.lower() not in PRINTABLE_EXTENSIONS:
        return fail(
            f"Unsupported file type '{resolved.suffix}'. "
            f"Supported: {', '.join(sorted(PRINTABLE_EXTENSIONS))}"
        )

    try:
        name = _resolve_printer_name(settings, printer_name)
    except Exception as exc:
        return fail(str(exc))

    try:
        print_settings = normalize_print_settings(
            copies=copies,
            orientation=orientation,
            paper=paper,
            paper_type=paper_type,
            quality=quality,
            color=color,
            duplex=duplex,
            page_range=page_range,
        )
    except ValueError as exc:
        return fail(str(exc))

    options = {
        "printer_name": name,
        **print_settings.to_dict(),
    }

    try:
        suffix = resolved.suffix.lower()
        if suffix in GDI_EXTENSIONS:
            print_with_gdi(resolved, name, print_settings)
        else:
            _print_office_with_devmode(resolved, name, print_settings)
        return ok({"file_path": str(resolved), **options})
    except Exception as exc:
        return fail(f"Print failed: {exc}")
