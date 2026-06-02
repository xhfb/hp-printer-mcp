from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import xml.etree.ElementTree as ET

from hp_printer_mcp.config import Settings, fail, ok

ESCL_NS = {
    "scan": "http://schemas.hp.com/imaging/escl/2011/05/03",
    "pwg": "http://www.pwg.org/schemas/2010/12/sm",
}


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_text(root: ET.Element, name: str) -> str | None:
    for elem in root.iter():
        if _local(elem.tag) == name and elem.text:
            return elem.text.strip()
    return None


def _find_all_text(root: ET.Element, name: str) -> list[str]:
    values: list[str] = []
    for elem in root.iter():
        if _local(elem.tag) == name and elem.text:
            values.append(elem.text.strip())
    return values


def _client(settings: Settings) -> httpx.Client:
    read_timeout = max(settings.escl_timeout_sec, settings.scan_poll_max_sec)
    timeout = httpx.Timeout(connect=30.0, read=read_timeout, write=30.0, pool=30.0)
    return httpx.Client(timeout=timeout, verify=False)


def _mime_for_format(fmt: str) -> str:
    mapping = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "pdf": "application/pdf",
    }
    key = fmt.lower().lstrip(".")
    if key not in mapping:
        raise ValueError(f"Unsupported format: {fmt}")
    return mapping[key]


def _ext_for_format(fmt: str) -> str:
    key = fmt.lower().lstrip(".")
    return "jpg" if key == "jpeg" else key


def get_scan_capabilities(settings: Settings) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    url = f"{settings.escl_base}/ScannerCapabilities"
    try:
        with _client(settings) as client:
            resp = client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except httpx.HTTPError as exc:
        return fail(f"Failed to fetch scanner capabilities: {exc}")

    resolutions: list[dict[str, int]] = []
    for elem in root.iter():
        if _local(elem.tag) == "DiscreteResolution":
            x = _find_text(elem, "XResolution")
            y = _find_text(elem, "YResolution")
            if x and y:
                resolutions.append({"x": int(x), "y": int(y)})

    formats = _find_all_text(root, "DocumentFormat")
    formats += _find_all_text(root, "DocumentFormatExt")
    formats = sorted({f for f in formats if f})

    sources: list[str] = []
    for elem in root.iter():
        if _local(elem.tag) == "InputSource":
            text = (elem.text or "").strip()
            if text:
                sources.append(text)

    color_spaces = _find_all_text(root, "ColorSpace")
    color_spaces = sorted({c for c in color_spaces if c})

    return ok(
        {
            "resolutions": resolutions,
            "document_formats": formats,
            "input_sources": sources or ["Platen", "Feeder"],
            "color_spaces": color_spaces or ["RGB24", "Grayscale8"],
        }
    )


def get_scanner_status(settings: Settings) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    url = f"{settings.escl_base}/ScannerStatus"
    try:
        with _client(settings) as client:
            resp = client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except httpx.HTTPError as exc:
        return fail(f"Failed to fetch scanner status: {exc}")

    state = _find_text(root, "ScannerState") or _find_text(root, "State") or "Unknown"
    adf_state = _find_text(root, "AdfState")
    adf_loaded = _find_text(root, "AdfLoaded")

    return ok(
        {
            "scanner_state": state,
            "adf_state": adf_state,
            "adf_loaded": adf_loaded,
            "is_idle": state.lower() == "idle",
        }
    )


# Portrait paper sizes in millimetres (width, height).
SCAN_PAPER_MM: dict[str, tuple[float, float]] = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "B4": (250.0, 353.0),
    "B5": (176.0, 250.0),
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
    "TABLOID": (279.4, 431.8),
    "EXECUTIVE": (184.2, 266.7),
}

SCAN_PAPER_ALIASES = {
    "MAX": None,
    "FULL": None,
    "AUTO": None,
}


def _mm_to_escl_units(mm: float) -> int:
    """Convert millimetres to eSCL ContentRegionUnits (1/300 inch)."""
    return round(mm / 25.4 * 300)


def normalize_scan_paper(paper: str) -> str | None:
    """Return canonical paper key, or None for full scan area (no ScanRegion)."""
    key = paper.strip().upper().replace(" ", "")
    if key in SCAN_PAPER_ALIASES:
        return None
    if key not in SCAN_PAPER_MM:
        supported = ", ".join(sorted({*SCAN_PAPER_MM, *SCAN_PAPER_ALIASES}))
        raise ValueError(f"paper must be one of: {supported}")
    return key


def scan_region_for_paper(
    paper: str,
    *,
    orientation: str = "portrait",
) -> tuple[int, int] | None:
    """Return (width, height) in eSCL units, or None for device maximum area."""
    paper_key = normalize_scan_paper(paper)
    if paper_key is None:
        return None
    width_mm, height_mm = SCAN_PAPER_MM[paper_key]
    if orientation.strip().lower() == "landscape":
        width_mm, height_mm = height_mm, width_mm
    return _mm_to_escl_units(width_mm), _mm_to_escl_units(height_mm)


def _adf_has_paper(adf_state: str | None, adf_loaded: str | None) -> bool:
    value = adf_loaded or adf_state
    if not value:
        return True
    low = str(value).lower()
    if low in ("false", "0", "empty", "unloaded") or "empty" in low:
        return False
    return low in ("true", "1", "loaded") or "loaded" in low


def _build_scan_settings_xml(
    *,
    source: str,
    dpi: int,
    color_mode: str,
    mime_type: str,
    paper: str = "A4",
    orientation: str = "portrait",
) -> bytes:
    input_source = "Feeder" if source.lower() in ("adf", "feeder") else "Platen"
    root = ET.Element(
        "scan:ScanSettings",
        {
            "xmlns:scan": ESCL_NS["scan"],
            "xmlns:pwg": ESCL_NS["pwg"],
        },
    )
    version = ET.SubElement(root, "pwg:Version")
    version.text = "2.63"
    src = ET.SubElement(root, "pwg:InputSource")
    src.text = input_source

    region = scan_region_for_paper(paper, orientation=orientation)
    if region is not None:
        width_u, height_u = region
        regions = ET.SubElement(root, "pwg:ScanRegions")
        regions.set(f"{{{ESCL_NS['pwg']}}}MustHonor", "true")
        scan_region = ET.SubElement(regions, "pwg:ScanRegion")
        units = ET.SubElement(scan_region, "pwg:ContentRegionUnits")
        units.text = "escl:ThreeHundredthsOfInches"
        ET.SubElement(scan_region, "pwg:Width").text = str(width_u)
        ET.SubElement(scan_region, "pwg:Height").text = str(height_u)
        ET.SubElement(scan_region, "pwg:XOffset").text = "0"
        ET.SubElement(scan_region, "pwg:YOffset").text = "0"

    content = ET.SubElement(root, "scan:ContentType")
    content.text = "TextAndPhoto"
    xres = ET.SubElement(root, "scan:XResolution")
    xres.text = str(dpi)
    yres = ET.SubElement(root, "scan:YResolution")
    yres.text = str(dpi)
    color = ET.SubElement(root, "scan:ColorMode")
    color.text = color_mode
    fmt = ET.SubElement(root, "pwg:DocumentFormat")
    fmt.text = mime_type
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _create_scan_job(client: httpx.Client, settings: Settings, payload: bytes) -> str:
    url = f"{settings.escl_base}/ScanJobs"
    resp = client.post(url, content=payload, headers={"Content-Type": "text/xml"})
    resp.raise_for_status()

    location = resp.headers.get("Location", "")
    if location:
        return location.rstrip("/").split("/")[-1]

    if resp.text.strip():
        root = ET.fromstring(resp.text)
        job_uri = _find_text(root, "JobUri") or _find_text(root, "JobUUID")
        if job_uri:
            return job_uri.rstrip("/").split("/")[-1]

    raise RuntimeError("Scan job created but no job id returned")


def _fetch_scan_pages_via_next_document(
    client: httpx.Client,
    settings: Settings,
    job_id: str,
) -> list[bytes]:
    """HP and many eSCL devices return pages from /ScanJobs/{id}/NextDocument only."""
    next_url = f"{settings.escl_base}/ScanJobs/{job_id}/NextDocument"
    pages: list[bytes] = []
    deadline = time.time() + settings.scan_poll_max_sec
    busy_retries = 0
    max_busy_retries = 120

    while time.time() < deadline:
        resp = client.get(next_url)
        if resp.status_code == 200 and resp.content:
            pages.append(resp.content)
            busy_retries = 0
            time.sleep(0.5)
            continue
        if resp.status_code in (404, 410):
            break
        if resp.status_code == 503:
            busy_retries += 1
            if busy_retries > max_busy_retries:
                raise TimeoutError("Timed out waiting for scanner to return a page (503)")
            time.sleep(settings.scan_poll_interval_sec)
            continue
        resp.raise_for_status()
        time.sleep(settings.scan_poll_interval_sec)

    if not pages:
        raise RuntimeError("Scan completed but no pages were returned")
    return pages


def _poll_scan_job(client: httpx.Client, settings: Settings, job_id: str) -> list[str]:
    job_url = f"{settings.escl_base}/ScanJobs/{job_id}"
    try:
        resp = client.get(job_url)
        if resp.status_code == 405:
            raise httpx.HTTPStatusError(
                "NextDocument only",
                request=resp.request,
                response=resp,
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        return [f"{job_url}/NextDocument"]

    deadline = time.time() + settings.scan_poll_max_sec
    document_urls: list[str] = []

    while time.time() < deadline:
        resp = client.get(job_url)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

        job_state = (_find_text(root, "JobState") or "").lower()
        for elem in root.iter():
            if _local(elem.tag) in ("ScanData", "ImageUrl", "DocumentUrl"):
                if elem.text:
                    document_urls.append(elem.text.strip())

        images = _find_all_text(root, "Images")
        for image_url in images:
            if image_url.startswith("/"):
                document_urls.append(f"{settings.base_url}{image_url}")
            elif image_url.startswith("http"):
                document_urls.append(image_url)

        if job_state in ("completed", "canceled", "aborted"):
            if job_state != "completed":
                raise RuntimeError(f"Scan job ended with state: {job_state}")
            break

        time.sleep(settings.scan_poll_interval_sec)
    else:
        raise TimeoutError("Timed out waiting for scan job to complete")

    if not document_urls:
        next_url = f"{job_url}/NextDocument"
        try:
            doc_resp = client.get(next_url)
            if doc_resp.status_code == 200 and doc_resp.content:
                document_urls.append(next_url)
        except httpx.HTTPError:
            pass

    if not document_urls:
        raise RuntimeError("Scan completed but no document URLs were found")

    return document_urls


def _download_documents(
    client: httpx.Client,
    settings: Settings,
    urls: list[str],
) -> list[bytes]:
    pages: list[bytes] = []
    for url in urls:
        if url.startswith("/"):
            url = f"{settings.base_url}{url}"
        resp = client.get(url)
        resp.raise_for_status()
        pages.append(resp.content)
    return pages


def _is_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def _merge_pdf_pages(pages: list[bytes]) -> bytes:
    """Merge scan pages into one PDF (HP often returns JPEG per page)."""
    from io import BytesIO

    if not pages:
        raise ValueError("No pages to merge")

    if all(_is_pdf(p) for p in pages):
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        for page_data in pages:
            reader = PdfReader(BytesIO(page_data))
            for page in reader.pages:
                writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()

    from PIL import Image

    images: list[Image.Image] = []
    for page_data in pages:
        if _is_pdf(page_data):
            raise RuntimeError("Mixed PDF and image pages are not supported")
        img = Image.open(BytesIO(page_data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        images.append(img)

    out = BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:])
    for img in images:
        img.close()
    return out.getvalue()


def _single_page_as_pdf(page_data: bytes) -> bytes:
    if _is_pdf(page_data):
        return page_data
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(page_data))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="PDF")
    img.close()
    return out.getvalue()


def scan_to_file(
    settings: Settings,
    *,
    source: str = "Platen",
    dpi: int = 300,
    format: str = "pdf",
    color_mode: str = "RGB24",
    paper: str = "A4",
    orientation: str = "portrait",
    output_path: str | None = None,
) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    status = get_scanner_status(settings)
    if not status.get("success"):
        return status

    scanner_data = status["data"]
    if not scanner_data.get("is_idle"):
        return fail(
            f"Scanner is not idle (state={scanner_data.get('scanner_state')})"
        )

    if source.lower() in ("adf", "feeder"):
        if not _adf_has_paper(
            scanner_data.get("adf_state"),
            scanner_data.get("adf_loaded"),
        ):
            return fail(
                f"ADF has no paper (adf_state={scanner_data.get('adf_state')}, "
                f"adf_loaded={scanner_data.get('adf_loaded')})"
            )

    try:
        mime_type = _mime_for_format(format)
        paper_key = normalize_scan_paper(paper)
        scan_region = scan_region_for_paper(paper, orientation=orientation)
    except ValueError as exc:
        return fail(str(exc))

    settings.scan_output_dir.mkdir(parents=True, exist_ok=True)
    if output_path:
        target = settings.ensure_allowed_path(output_path, for_write=True)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = _ext_for_format(format)
        target = settings.scan_output_dir / f"scan_{stamp}.{ext}"
        target = settings.ensure_allowed_path(target, for_write=True)

    payload = _build_scan_settings_xml(
        source=source,
        dpi=dpi,
        color_mode=color_mode,
        mime_type=mime_type,
        paper=paper,
        orientation=orientation,
    )

    try:
        with _client(settings) as client:
            job_id = _create_scan_job(client, settings, payload)
            doc_urls = _poll_scan_job(client, settings, job_id)
            if len(doc_urls) == 1 and doc_urls[0].endswith("/NextDocument"):
                pages = _fetch_scan_pages_via_next_document(client, settings, job_id)
            else:
                pages = _download_documents(client, settings, doc_urls)
    except (httpx.HTTPError, TimeoutError, RuntimeError) as exc:
        return fail(f"Scan failed: {exc}")

    fmt_key = format.lower().lstrip(".")
    if fmt_key == "pdf":
        content = _merge_pdf_pages(pages) if len(pages) > 1 else _single_page_as_pdf(pages[0])
    elif len(pages) == 1:
        content = pages[0]
    else:
        content = pages[0]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    result: dict[str, Any] = {
        "output_path": str(target),
        "page_count": len(pages),
        "job_id": job_id,
        "source": source,
        "dpi": dpi,
        "format": fmt_key,
        "paper": paper_key or "MAX",
        "orientation": orientation.strip().lower(),
    }
    if scan_region is not None:
        result["scan_region_units"] = {
            "width": scan_region[0],
            "height": scan_region[1],
        }
    return ok(result)
