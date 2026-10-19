from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import base64

import httpx
import xml.etree.ElementTree as ET

from hp_printer_mcp.config import Settings, fail, ok
from hp_printer_mcp.http_util import make_client

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


def _elements_named(root: ET.Element, name: str) -> list[ET.Element]:
    return [elem for elem in root.iter() if _local(elem.tag) == name]


def _int_desc(elem: ET.Element, name: str) -> int | None:
    text = _find_text(elem, name)
    if text and text.lstrip("-").isdigit():
        return int(text)
    return None


def _unique(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        if value and value not in found:
            found.append(value)
    return found


def _collect_resolutions(elem: ET.Element) -> list[dict[str, int]]:
    found: list[dict[str, int]] = []
    for node in elem.iter():
        if _local(node.tag) != "DiscreteResolution":
            continue
        x = _find_text(node, "XResolution")
        y = _find_text(node, "YResolution")
        if x and y:
            item = {"x": int(x), "y": int(y)}
            if item not in found:
                found.append(item)
    return found


def _source_record(elem: ET.Element) -> dict[str, Any]:
    return {
        "resolutions": _collect_resolutions(elem),
        "document_formats": sorted(
            {
                item
                for item in _find_all_text(elem, "DocumentFormat")
                + _find_all_text(elem, "DocumentFormatExt")
                if item
            }
        ),
        "color_modes": _unique(_find_all_text(elem, "ColorMode")),
        "color_spaces": _unique(_find_all_text(elem, "ColorSpace")),
        "min_width": _int_desc(elem, "MinWidth"),
        "max_width": _int_desc(elem, "MaxWidth"),
        "min_height": _int_desc(elem, "MinHeight"),
        "max_height": _int_desc(elem, "MaxHeight"),
    }


def _merge_sources(records: list[dict[str, Any]]) -> dict[str, Any]:
    merged = _source_record(ET.Element("empty"))
    merged["resolutions"] = []
    for record in records:
        for item in record["resolutions"]:
            if item not in merged["resolutions"]:
                merged["resolutions"].append(item)
        for key in ("document_formats", "color_modes", "color_spaces"):
            merged[key] = sorted(set(merged[key]) | set(record[key]))
        for key in ("min_width", "min_height"):
            values = [value for value in (merged[key], record[key]) if value is not None]
            merged[key] = min(values) if values else None
        for key in ("max_width", "max_height"):
            values = [value for value in (merged[key], record[key]) if value is not None]
            merged[key] = max(values) if values else None
    return merged


def parse_scanner_capabilities(root: ET.Element) -> dict[str, Any]:
    """Flatten eSCL ScannerCapabilities, keeping Platen and Feeder limits apart."""
    sources: dict[str, dict[str, Any]] = {}
    platen = _elements_named(root, "PlatenInputCaps")
    if platen:
        sources["Platen"] = _merge_sources([_source_record(elem) for elem in platen])
    feeder = _elements_named(root, "AdfSimplexInputCaps") + _elements_named(
        root, "AdfDuplexInputCaps"
    )
    if not feeder:
        feeder = _elements_named(root, "AdfInputCaps")
    if feeder:
        sources["Feeder"] = _merge_sources([_source_record(elem) for elem in feeder])

    resolutions = _collect_resolutions(root)
    formats = sorted(
        {
            item
            for item in _find_all_text(root, "DocumentFormat")
            + _find_all_text(root, "DocumentFormatExt")
            if item
        }
    )
    input_sources = _unique(_find_all_text(root, "InputSource")) or ["Platen", "Feeder"]
    return {
        "resolutions": resolutions,
        "document_formats": formats,
        "input_sources": input_sources,
        "color_spaces": _unique(_find_all_text(root, "ColorSpace")) or ["RGB24", "Grayscale8"],
        "color_modes": _unique(_find_all_text(root, "ColorMode")),
        "sources": sources,
    }


def _scan_source_key(source: str) -> str:
    key = source.strip().lower()
    if key in {"platen", "flatbed", "glass"}:
        return "Platen"
    if key in {"adf", "feeder"}:
        return "Feeder"
    raise ValueError("source must be Platen or Feeder/ADF")


def _match_token(value: str, choices: list[str]) -> str | None:
    for choice in choices:
        if choice.lower() == value.lower():
            return choice
    return None


def validate_scan_request(
    caps: dict[str, Any],
    *,
    source: str,
    dpi: int,
    format: str,
    color_mode: str,
    paper: str,
    orientation: str,
) -> dict[str, Any]:
    """Reject dpi, format, color, and paper the selected source cannot do."""
    source_key = _scan_source_key(source)
    sources = caps.get("sources") or {}
    if sources:
        if source_key not in sources:
            available = ", ".join(sorted(sources)) or "none"
            raise ValueError(f"Scanner has no {source_key} source. Available: {available}")
        selected = sources[source_key]
    else:
        selected = None

    mime = _mime_for_format(format)
    formats = (selected or {}).get("document_formats") or caps.get("document_formats") or []
    if formats and mime not in formats:
        friendly = ", ".join(formats)
        raise ValueError(
            f"format {format!r} ({mime}) is not supported on {source_key}. "
            f"Scanner accepts: {friendly}"
        )

    resolutions = (selected or {}).get("resolutions") or caps.get("resolutions") or []
    allowed_dpi = sorted({item["x"] for item in resolutions if item.get("x") == item.get("y")})
    if allowed_dpi and dpi not in allowed_dpi:
        raise ValueError(
            f"{source_key} does not support {dpi} dpi. Supported dpi: "
            + ", ".join(str(item) for item in allowed_dpi)
        )

    color_choices = (selected or {}).get("color_modes") or caps.get("color_modes") or []
    if not color_choices:
        color_choices = (selected or {}).get("color_spaces") or caps.get("color_spaces") or []
    canonical_color = color_mode
    if color_choices:
        matched = _match_token(color_mode, color_choices)
        if matched is None:
            raise ValueError(
                f"color_mode {color_mode!r} is not supported on {source_key}. "
                f"Supported: {', '.join(color_choices)}"
            )
        canonical_color = matched

    region = scan_region_for_paper(paper, orientation=orientation)
    limits = selected or {}
    if region is not None and limits:
        width, height = region
        checks = (
            ("max_width", width, "wider"),
            ("max_height", height, "taller"),
        )
        for limit_name, actual, word in checks:
            limit = limits.get(limit_name)
            if limit is not None and actual > limit:
                raise ValueError(
                    f"paper {paper!r} is {word} than the {source_key} scan area "
                    f"({actual} > {limit} in 1/300 inch units)"
                )
        for limit_name, actual, word in (
            ("min_width", width, "narrower"),
            ("min_height", height, "shorter"),
        ):
            limit = limits.get(limit_name)
            if limit is not None and actual < limit:
                raise ValueError(
                    f"paper {paper!r} is {word} than the {source_key} minimum "
                    f"({actual} < {limit} in 1/300 inch units)"
                )

    return {"mime_type": mime, "color_mode": canonical_color, "source_key": source_key}


def _client(settings: Settings) -> httpx.Client:
    return make_client(settings)


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

    return ok(parse_scanner_capabilities(root))


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


def _merge_pdf_pages(pages: list[bytes], *, dpi: int = 300) -> bytes:
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
    try:
        return _save_images_as_pdf(images, dpi=dpi)
    finally:
        for img in images:
            img.close()


def _save_images_as_pdf(images: list, *, dpi: int) -> bytes:
    """Write scan images at their scan resolution so the page is A4, not 1 px = 1 pt."""
    from io import BytesIO

    if dpi < 1:
        raise ValueError("dpi must be >= 1")
    resolution = float(dpi)
    for img in images:
        img.info["dpi"] = (resolution, resolution)
    out = BytesIO()
    images[0].save(
        out,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=resolution,
    )
    return out.getvalue()


def _single_page_as_pdf(page_data: bytes, *, dpi: int = 300) -> bytes:
    if _is_pdf(page_data):
        return page_data
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(page_data))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    try:
        return _save_images_as_pdf([img], dpi=dpi)
    finally:
        img.close()


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
    include_base64: bool | None = None,
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

    caps = get_scan_capabilities(settings)
    if not caps.get("success"):
        return caps

    try:
        checked = validate_scan_request(
            caps["data"],
            source=source,
            dpi=dpi,
            format=format,
            color_mode=color_mode,
            paper=paper,
            orientation=orientation,
        )
        mime_type = checked["mime_type"]
        color_mode = checked["color_mode"]
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
    warnings: list[str] = []
    if fmt_key == "pdf":
        content = (
            _merge_pdf_pages(pages, dpi=dpi)
            if len(pages) > 1
            else _single_page_as_pdf(pages[0], dpi=dpi)
        )
    elif len(pages) == 1:
        content = pages[0]
    else:
        content = pages[0]
        warnings.append(
            f"Scanner returned {len(pages)} JPEG pages; only page 1 was saved. "
            "Use format=pdf for a multi-page document."
        )

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
    if warnings:
        result["warnings"] = warnings
    if scan_region is not None:
        result["scan_region_units"] = {
            "width": scan_region[0],
            "height": scan_region[1],
        }
    want_b64 = (
        settings.include_scan_base64 if include_base64 is None else include_base64
    )
    if want_b64:
        # Cap base64 payload for very large scans
        max_b64_bytes = settings.max_upload_mb * 1024 * 1024
        if len(content) <= max_b64_bytes:
            result["content_base64"] = base64.b64encode(content).decode("ascii")
            result["content_bytes"] = len(content)
        else:
            result["content_base64"] = None
            result["content_base64_omitted"] = (
                f"scan larger than HP_MAX_UPLOAD_MB ({settings.max_upload_mb})"
            )
    return ok(result)
