from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx

from hp_printer_mcp.config import Settings, fail, ok
from hp_printer_mcp.http_util import make_client
from hp_printer_mcp.ipp_client import IppClient, IppError
from hp_printer_mcp.job_input import JobInputError, resolve_print_input
from hp_printer_mcp.print_options import normalize_print_settings
from hp_printer_mcp.rasterize import rasterize_to_jpegs

# IPP print-quality enums
QUALITY_MAP = {"draft": 3, "normal": 4, "high": 5, "best": 5}
# orientation-requested: 3=portrait, 4=landscape
ORIENTATION_MAP = {"portrait": 3, "landscape": 4}
SIDES_MAP = {
    "none": "one-sided",
    "long_edge": "two-sided-long-edge",
    "short_edge": "two-sided-short-edge",
}
MEDIA_MAP = {
    "A3": "iso_a3_297x420mm",
    "A4": "iso_a4_210x297mm",
    "A5": "iso_a5_148x210mm",
    "B4": "iso_b4_250x353mm",
    "B5": "iso_b5_176x250mm",
    "LETTER": "na_letter_8.5x11in",
    "LEGAL": "na_legal_8.5x14in",
    "TABLOID": "na_ledger_11x17in",
    "EXECUTIVE": "na_executive_7.25x10.5in",
}

JOB_STATE_NAMES = {
    3: "pending",
    4: "pending-held",
    5: "processing",
    6: "processing-stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}


def _ipp_client(settings: Settings, client: httpx.Client) -> IppClient:
    return IppClient(
        ipp_uri=settings.ipp_uri,
        client=client,
        username=settings.ipp_username,
        password=settings.ipp_password,
    )


def _choose_document_format(formats: list[str]) -> str:
    normalized = [str(f).lower() for f in formats]
    for candidate in ("image/jpeg", "image/pwg-raster", "image/urf", "application/pdf"):
        if candidate in normalized:
            return candidate
    if normalized:
        return normalized[0]
    return "image/jpeg"


def _printer_formats(ipp: IppClient) -> list[str]:
    resp = ipp.get_printer_attributes(
        [
            "document-format-supported",
            "printer-state",
            "printer-state-reasons",
            "sides-supported",
        ]
    )
    values = resp.attributes.get("document-format-supported") or []
    return [str(v) for v in values]


def is_printer_ready(settings: Settings) -> bool:
    if not settings.printer_host:
        return False
    try:
        with make_client(settings, timeout=10.0) as client:
            ipp = _ipp_client(settings, client)
            resp = ipp.get_printer_attributes(["printer-state", "printer-state-reasons"])
            state = resp.first("printer-state")
            # 3=idle, 4=processing, 5=stopped
            return state in (3, 4)
    except Exception:
        return False


def print_queue_count(settings: Settings) -> int:
    result = list_print_jobs(settings)
    if not result.get("success"):
        return 0
    return len(result["data"].get("jobs") or [])


def list_print_jobs(settings: Settings, *, printer_name: str | None = None) -> dict[str, Any]:
    del printer_name  # unused; IPP URI is authoritative
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")
    try:
        with make_client(settings, timeout=15.0) as client:
            ipp = _ipp_client(settings, client)
            resp = ipp.get_jobs()
    except (httpx.HTTPError, IppError) as exc:
        return fail(
            f"Failed to list IPP jobs: {exc}",
            data={"printer_uri": settings.ipp_uri, "partial": True, "jobs": []},
        )

    job_ids = resp.attributes.get("job-id") or []
    names = resp.attributes.get("job-name") or []
    states = resp.attributes.get("job-state") or []
    users = resp.attributes.get("job-originating-user-name") or []
    created = resp.attributes.get("time-at-creation") or []

    jobs = []
    for i, job_id in enumerate(job_ids):
        state_val = states[i] if i < len(states) else None
        jobs.append(
            {
                "job_id": job_id,
                "document": names[i] if i < len(names) else None,
                "status": JOB_STATE_NAMES.get(state_val, state_val),
                "status_code": state_val,
                "pages": None,
                "submitted": created[i] if i < len(created) else None,
                "username": users[i] if i < len(users) else None,
            }
        )

    return ok(
        {
            "printer_uri": settings.ipp_uri,
            "printer_name": settings.printer_name,
            "jobs": jobs,
            "partial": False,
        }
    )


def cancel_print_job(
    settings: Settings,
    *,
    job_id: int,
    printer_name: str | None = None,
) -> dict[str, Any]:
    del printer_name
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")
    try:
        with make_client(settings, timeout=15.0) as client:
            ipp = _ipp_client(settings, client)
            ipp.cancel_job(job_id)
        return ok(
            {
                "printer_uri": settings.ipp_uri,
                "job_id": job_id,
                "cancelled": True,
            }
        )
    except (httpx.HTTPError, IppError) as exc:
        return fail(f"Failed to cancel IPP job: {exc}")


def get_ipp_printer_state(settings: Settings) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")
    try:
        with make_client(settings, timeout=10.0) as client:
            ipp = _ipp_client(settings, client)
            resp = ipp.get_printer_attributes(
                [
                    "printer-state",
                    "printer-state-reasons",
                    "printer-make-and-model",
                    "document-format-supported",
                ]
            )
        state = resp.first("printer-state")
        return ok(
            {
                "printer_uri": settings.ipp_uri,
                "printer_state": state,
                "printer_state_name": {3: "idle", 4: "processing", 5: "stopped"}.get(
                    state, state
                ),
                "printer_state_reasons": resp.attributes.get("printer-state-reasons"),
                "make_and_model": resp.first("printer-make-and-model"),
                "document_format_supported": resp.attributes.get(
                    "document-format-supported"
                ),
                "ready": state in (3, 4),
            }
        )
    except (httpx.HTTPError, IppError) as exc:
        return fail(f"Failed to read IPP printer state: {exc}")


def print_file(
    settings: Settings,
    *,
    file_path: str | None = None,
    content_base64: str | None = None,
    filename: str | None = None,
    url: str | None = None,
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
    del printer_name  # IPP URI is authoritative
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    warnings: list[str] = []
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

    if print_settings.paper_type != "plain":
        warnings.append(
            f"paper_type={print_settings.paper_type!r} is not mapped to IPP; ignored"
        )

    job_dir: Path | None = None
    try:
        source, job_dir = resolve_print_input(
            settings,
            file_path=file_path,
            content_base64=content_base64,
            filename=filename,
            url=url,
        )
    except JobInputError as exc:
        return fail(str(exc))

    try:
        with make_client(settings, timeout=120.0) as client:
            ipp = _ipp_client(settings, client)
            formats = _printer_formats(ipp)
            chosen = _choose_document_format(formats)

            sides = SIDES_MAP[print_settings.duplex]
            media = MEDIA_MAP.get(print_settings.paper)
            color_mode = (
                "monochrome"
                if print_settings.color == "monochrome"
                else "color"
            )
            print_quality = QUALITY_MAP.get(print_settings.quality, 4)
            orientation_req = ORIENTATION_MAP.get(print_settings.orientation, 3)

            job_ids: list[int] = []

            if chosen == "application/pdf" and source.suffix.lower() == ".pdf":
                document = source.read_bytes()
                resp = ipp.print_job(
                    document,
                    document_format="application/pdf",
                    job_name=source.name,
                    copies=print_settings.copies,
                    sides=sides,
                    media=media,
                    print_color_mode=color_mode,
                    print_quality=print_quality,
                    orientation_requested=orientation_req,
                )
                job_id = resp.first("job-id")
                if job_id is not None:
                    job_ids.append(job_id)
                document_format_used = "application/pdf"
                page_count = None
            else:
                # Smart Tank path: rasterize to JPEG pages
                if chosen != "image/jpeg":
                    warnings.append(
                        f"Preferred format {chosen} unavailable/unused; sending image/jpeg"
                    )
                pages = rasterize_to_jpegs(
                    source,
                    paper=print_settings.paper,
                    orientation=print_settings.orientation,
                    color=print_settings.color,
                    page_range=print_settings.page_range,
                )
                if not pages:
                    return fail("Rasterizer produced no pages")
                for index, page_bytes in enumerate(pages):
                    resp = ipp.print_job(
                        page_bytes,
                        document_format="image/jpeg",
                        job_name=f"{source.name}#p{index + 1}",
                        copies=print_settings.copies,
                        sides=sides,
                        media=media,
                        print_color_mode=color_mode,
                        print_quality=print_quality,
                        orientation_requested=orientation_req,
                    )
                    job_id = resp.first("job-id")
                    if job_id is not None:
                        job_ids.append(job_id)
                document_format_used = "image/jpeg"
                page_count = len(pages)

        data = {
            "file_path": str(source),
            "filename": source.name,
            "printer_uri": settings.ipp_uri,
            "printer_name": settings.printer_name,
            "job_id": job_ids[0] if len(job_ids) == 1 else None,
            "job_ids": job_ids,
            "document_format_used": document_format_used,
            "page_count": page_count,
            "warnings": warnings,
            **print_settings.to_dict(),
        }
        return ok(data)
    except (httpx.HTTPError, IppError, ValueError, OSError) as exc:
        return fail(f"Print failed: {exc}")
    finally:
        if job_dir is not None:
            shutil.rmtree(job_dir, ignore_errors=True)
