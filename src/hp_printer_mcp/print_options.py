from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass
from typing import Any

from hp_printer_mcp.media import resolve_media, resolve_media_type


@dataclass
class PrintSettings:
    copies: int = 1
    orientation: str = "portrait"
    paper: str = "A4"
    paper_type: str = "plain"
    quality: str = "normal"
    color: str = "color"
    duplex: str = "none"
    page_range: str = "all"
    borderless: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ORIENTATIONS = {"portrait", "landscape"}
COLORS = {
    "color",
    "monochrome",
    "grayscale",
    "bw",
    "black_and_white",
    "auto",
    "auto-monochrome",
    "auto_monochrome",
}
DUPLEX_MODES = {"none", "long_edge", "short_edge", "simplex", "duplex_long", "duplex_short"}
QUALITIES = {"draft", "normal", "high", "best"}
PAPER_TYPES = {"plain", "photo", "cardstock", "envelope", "labels", "transparency"}

PAPER_SIZES = {
    "A3": 8,
    "A4": 9,
    "A5": 11,
    "B4": 12,
    "B5": 13,
    "LETTER": 1,
    "LEGAL": 5,
    "TABLOID": 3,
    "EXECUTIVE": 7,
    "STATEMENT": 6,
    "FOLIO": 14,
    "QUARTO": 15,
    "10X14": 16,
    "11X17": 17,
    "NOTE": 18,
    "ENV_9": 19,
    "ENV_10": 20,
    "ENV_11": 21,
    "ENV_12": 22,
    "ENV_14": 23,
    "C5": 28,
    "C3": 29,
    "C4": 30,
    "C6": 31,
    "DL": 27,
}


def normalize_print_settings(
    *,
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    page_range: str = "all",
    borderless: bool = False,
) -> PrintSettings:
    if copies < 1:
        raise ValueError("copies must be >= 1")

    orientation_key = orientation.strip().lower()
    if orientation_key not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of: {', '.join(sorted(ORIENTATIONS))}")

    media = resolve_media(paper)
    paper_key = media.name
    paper_type_key, _media_type = resolve_media_type(paper_type)

    quality_key = quality.strip().lower()
    if quality_key not in QUALITIES:
        supported = ", ".join(sorted(QUALITIES))
        raise ValueError(f"quality must be one of: {supported}")

    color_key = color.strip().lower().replace("_", "-")
    if color_key in {"bw", "black-and-white", "black_and_white", "grayscale", "grey", "gray"}:
        color_key = "monochrome"
    if color_key in {"auto-mono", "automonochrome"}:
        color_key = "auto-monochrome"
    if color_key not in {"color", "monochrome", "auto", "auto-monochrome"}:
        raise ValueError("color must be 'color', 'monochrome', 'auto', or 'auto-monochrome'")

    duplex_key = duplex.strip().lower()
    duplex_aliases = {
        "simplex": "none",
        "single": "none",
        "duplex_long": "long_edge",
        "long": "long_edge",
        "long-edge": "long_edge",
        "duplex_short": "short_edge",
        "short": "short_edge",
        "short-edge": "short_edge",
    }
    duplex_key = duplex_aliases.get(duplex_key, duplex_key)
    if duplex_key not in {"none", "long_edge", "short_edge"}:
        raise ValueError(
            "duplex must be one of: none, long_edge, short_edge "
            "(沿长边翻折=long_edge, 沿短边翻折=short_edge)"
        )

    page_range_key = page_range.strip() or "all"
    if page_range_key.lower() != "all" and not validate_page_range_spec(page_range_key):
        raise ValueError(
            f"Invalid page_range {page_range_key!r}; use 'all' or e.g. '1-4,7'"
        )

    if isinstance(borderless, str):
        borderless_value = borderless.strip().lower() in {"1", "true", "yes", "on"}
    elif isinstance(borderless, bool):
        borderless_value = borderless
    else:
        raise ValueError("borderless must be true or false")

    return PrintSettings(
        copies=copies,
        orientation=orientation_key,
        paper=paper_key,
        paper_type=paper_type_key,
        quality=quality_key,
        color=color_key,
        duplex=duplex_key,
        page_range=page_range_key,
        borderless=borderless_value,
    )


def parse_page_range(page_range: str, *, total_pages: int) -> list[int]:
    """Return zero-based page indices for a range like '1-3,5'."""
    spec = page_range.strip()
    if not spec or spec.lower() == "all":
        return list(range(total_pages))

    indices: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s.strip())
            end = int(end_s.strip())
            if start < 1 or end < start:
                raise ValueError(f"Invalid page range segment: {part}")
            indices.extend(range(start - 1, end))
        else:
            page = int(part)
            if page < 1:
                raise ValueError(f"Invalid page number: {page}")
            indices.append(page - 1)

    unique = sorted(set(indices))
    if total_pages > 0 and any(i >= total_pages for i in unique):
        raise ValueError(
            f"Page range {page_range!r} exceeds document page count ({total_pages})"
        )
    return unique


def _win32_constants() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    import win32con

    return {
        "DM_ORIENTATION": win32con.DM_ORIENTATION,
        "DM_PAPERSIZE": win32con.DM_PAPERSIZE,
        "DM_COPIES": win32con.DM_COPIES,
        "DM_COLOR": win32con.DM_COLOR,
        "DM_DUPLEX": win32con.DM_DUPLEX,
        "DM_PRINTQUALITY": win32con.DM_PRINTQUALITY,
        "DM_MEDIATYPE": getattr(win32con, "DM_MEDIATYPE", 0),
        "DMORIENT_PORTRAIT": win32con.DMORIENT_PORTRAIT,
        "DMORIENT_LANDSCAPE": win32con.DMORIENT_LANDSCAPE,
        "DMCOLOR_COLOR": win32con.DMCOLOR_COLOR,
        "DMCOLOR_MONOCHROME": win32con.DMCOLOR_MONOCHROME,
        "DMDUP_SIMPLEX": win32con.DMDUP_SIMPLEX,
        "DMDUP_HORIZONTAL": win32con.DMDUP_HORIZONTAL,
        "DMDUP_VERTICAL": win32con.DMDUP_VERTICAL,
        "DMRES_DRAFT": win32con.DMRES_DRAFT,
        "DMRES_LOW": win32con.DMRES_LOW,
        "DMRES_MEDIUM": win32con.DMRES_MEDIUM,
        "DMRES_HIGH": win32con.DMRES_HIGH,
    }


PAPER_TYPE_MEDIA = {
    "plain": 1,
    "photo": 2,
    "cardstock": 3,
    "envelope": 4,
    "labels": 5,
    "transparency": 6,
}


def apply_settings_to_devmode(devmode: Any, settings: PrintSettings) -> Any:
    """Apply PrintSettings to a pywin32 DEVMODE object."""
    const = _win32_constants()
    if not const:
        raise RuntimeError("DEVMODE is only available on Windows")

    fields = int(devmode.Fields)
    fields |= const["DM_ORIENTATION"]
    fields |= const["DM_PAPERSIZE"]
    fields |= const["DM_COPIES"]
    fields |= const["DM_COLOR"]
    fields |= const["DM_DUPLEX"]
    fields |= const["DM_PRINTQUALITY"]
    if const["DM_MEDIATYPE"]:
        fields |= const["DM_MEDIATYPE"]

    devmode.Fields = fields
    devmode.Orientation = (
        const["DMORIENT_LANDSCAPE"]
        if settings.orientation == "landscape"
        else const["DMORIENT_PORTRAIT"]
    )
    if settings.paper not in PAPER_SIZES:
        raise ValueError(
            f"Windows DEVMODE path has no DMPAPER id for paper {settings.paper!r}"
        )
    devmode.PaperSize = PAPER_SIZES[settings.paper]
    devmode.Copies = settings.copies
    devmode.Color = (
        const["DMCOLOR_MONOCHROME"]
        if settings.color == "monochrome"
        else const["DMCOLOR_COLOR"]
    )

    duplex_map = {
        "none": const["DMDUP_SIMPLEX"],
        "long_edge": const["DMDUP_VERTICAL"],
        "short_edge": const["DMDUP_HORIZONTAL"],
    }
    devmode.Duplex = duplex_map[settings.duplex]

    quality_map = {
        "draft": const["DMRES_DRAFT"],
        "normal": const["DMRES_MEDIUM"],
        "high": const["DMRES_HIGH"],
        "best": const["DMRES_HIGH"],
    }
    devmode.PrintQuality = quality_map[settings.quality]

    if const["DM_MEDIATYPE"]:
        devmode.MediaType = PAPER_TYPE_MEDIA.get(settings.paper_type, 1)

    return devmode


def get_printer_devmode(printer_name: str, settings: PrintSettings) -> Any:
    if sys.platform != "win32":
        raise RuntimeError("Printing is only supported on Windows")
    import win32con
    import win32print

    handle = win32print.OpenPrinter(printer_name)
    try:
        devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
        if devmode is None:
            raise RuntimeError(f"Printer {printer_name!r} has no DEVMODE")
        return apply_settings_to_devmode(devmode, settings)
    finally:
        win32print.ClosePrinter(handle)


def validate_page_range_spec(page_range: str) -> bool:
    if not page_range or page_range.strip().lower() == "all":
        return True
    return bool(re.fullmatch(r"[\d,\-\s]+", page_range.strip()))
