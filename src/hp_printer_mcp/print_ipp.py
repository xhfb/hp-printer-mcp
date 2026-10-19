from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from hp_printer_mcp.config import Settings, fail, ok
from hp_printer_mcp.http_util import make_client
from hp_printer_mcp.ipp_client import IppClient, IppError
from hp_printer_mcp.job_input import JobInputError, resolve_print_input
from hp_printer_mcp.print_options import normalize_print_settings
from hp_printer_mcp.printer_caps import fetch_printer_caps, resolve_print_ticket
from hp_printer_mcp.pwg_raster import encode_pwg_raster
from hp_printer_mcp.rasterize import rasterize_to_images, to_feed_orientation

JOB_STATE_NAMES = {
    3: "pending",
    4: "pending-held",
    5: "processing",
    6: "processing-stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}


def collated_raster_pages(
    pages: list[Image.Image],
    copies: int,
    *,
    duplex: bool,
) -> tuple[list[Image.Image], list[Image.Image]]:
    """Repeat a document so copies are already in the raster.

    This Smart Tank records IPP ``copies`` and the page-header ``NumCopies``
    but still prints the raster once. Odd duplex copies get a blank back so
    the next copy starts on a front side. Returned extras must be closed by
    the caller; the repeated list only references those images.
    """
    if copies < 1:
        raise ValueError("copies must be >= 1")
    if copies == 1 or not pages:
        return list(pages), []
    group = list(pages)
    extras: list[Image.Image] = []
    if duplex and len(group) % 2 == 1:
        blank = Image.new(group[0].mode, group[0].size, "white")
        extras.append(blank)
        group.append(blank)
    return group * copies, extras


def _ipp_client(settings: Settings, client: httpx.Client) -> IppClient:
    return IppClient(
        ipp_uri=settings.ipp_uri,
        client=client,
        username=settings.ipp_username,
        password=settings.ipp_password,
    )


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
    borderless: bool = False,
    printer_name: str | None = None,
) -> dict[str, Any]:
    del printer_name  # IPP URI is authoritative
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

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
            borderless=borderless,
        )
    except ValueError as exc:
        return fail(str(exc))

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
            caps = fetch_printer_caps(ipp)
            ticket = resolve_print_ticket(
                print_settings,
                caps,
                source_suffix=source.suffix.lower(),
            )
            warnings = list(ticket.warnings)
            job_kwargs = {
                "copies": ticket.copies,
                "sides": ticket.sides,
                "media": ticket.media_keyword,
                "media_col": ticket.media_col,
                "print_color_mode": ticket.color_mode,
                "print_quality": ticket.quality,
                "print_scaling": ticket.print_scaling,
            }
            job_ids: list[int] = []

            if ticket.document_format == "application/pdf":
                resp = ipp.print_job(
                    source.read_bytes(),
                    document_format="application/pdf",
                    job_name=source.name,
                    **job_kwargs,
                )
                job_id = resp.first("job-id")
                if job_id is not None:
                    job_ids.append(int(job_id))
                page_count = None
            elif ticket.document_format == "image/pwg-raster":
                images = rasterize_to_images(
                    source,
                    paper=print_settings.paper,
                    orientation=print_settings.orientation,
                    color=print_settings.color,
                    page_range=print_settings.page_range,
                    dpi=ticket.dpi,
                )
                if not images:
                    return fail("Rasterizer produced no pages")
                feed_pages: list[Any] = []
                extra_pages: list[Image.Image] = []
                try:
                    for image in images:
                        oriented = to_feed_orientation(image, print_settings.orientation)
                        if oriented is not image:
                            image.close()
                        feed_pages.append(oriented)
                    raster_pages, extra_pages = collated_raster_pages(
                        feed_pages,
                        ticket.copies,
                        duplex=print_settings.duplex != "none",
                    )
                    document = encode_pwg_raster(
                        raster_pages,
                        dpi=ticket.dpi,
                        media_keyword=ticket.media_keyword,
                        media_type=ticket.media_type,
                        width_hundredths=ticket.x,
                        height_hundredths=ticket.y,
                        margins=ticket.margins,
                        duplex=print_settings.duplex != "none",
                        tumble=print_settings.duplex == "short_edge",
                        sheet_back=ticket.sheet_back,
                        pwg_type=ticket.pwg_type,
                        print_quality=ticket.quality,
                        copies=1,
                    )
                finally:
                    closed = {id(image) for image in feed_pages}
                    for image in feed_pages:
                        image.close()
                    for image in extra_pages:
                        image.close()
                    for image in images:
                        if id(image) not in closed:
                            image.close()
                # Copies are already repeated in the raster. Leaving IPP copies
                # at 2 made jobs 6 and 7 record copies=2 and still eject one sheet.
                pwg_kwargs = dict(job_kwargs)
                pwg_kwargs["copies"] = 1
                resp = ipp.print_job(
                    document,
                    document_format="image/pwg-raster",
                    job_name=source.name,
                    **pwg_kwargs,
                )
                job_id = resp.first("job-id")
                if job_id is not None:
                    job_ids.append(int(job_id))
                page_count = len(feed_pages)
            else:
                images = rasterize_to_images(
                    source,
                    paper=print_settings.paper,
                    orientation=print_settings.orientation,
                    color=print_settings.color,
                    page_range=print_settings.page_range,
                    dpi=ticket.dpi,
                )
                if not images:
                    return fail("Rasterizer produced no pages")
                # JPEG is one image per IPP job, so duplex and collation cannot work.
                from io import BytesIO

                page_count = len(images)
                try:
                    for index, image in enumerate(images):
                        oriented = to_feed_orientation(image, print_settings.orientation)
                        buf = BytesIO()
                        oriented.save(buf, format="JPEG", quality=85, optimize=True)
                        if oriented is not image:
                            oriented.close()
                        resp = ipp.print_job(
                            buf.getvalue(),
                            document_format="image/jpeg",
                            job_name=f"{source.name}#p{index + 1}",
                            **job_kwargs,
                        )
                        job_id = resp.first("job-id")
                        if job_id is not None:
                            job_ids.append(int(job_id))
                finally:
                    for image in images:
                        image.close()

        data = {
            "file_path": str(source),
            "filename": source.name,
            "printer_uri": settings.ipp_uri,
            "printer_name": settings.printer_name,
            "job_id": job_ids[0] if len(job_ids) == 1 else None,
            "job_ids": job_ids,
            "document_format_used": ticket.document_format,
            "page_count": page_count,
            "raster_dpi": ticket.dpi if ticket.document_format != "application/pdf" else None,
            "media": ticket.media_keyword,
            "media_type": ticket.media_type,
            "warnings": warnings,
            **print_settings.to_dict(),
        }
        return ok(data)
    except (httpx.HTTPError, IppError, ValueError, OSError) as exc:
        return fail(f"Print failed: {exc}")
    finally:
        if job_dir is not None:
            shutil.rmtree(job_dir, ignore_errors=True)
