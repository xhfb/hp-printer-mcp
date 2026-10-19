"""Read IPP printer capabilities and turn a print request into a job ticket."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hp_printer_mcp.ipp_client import (
    TAG_BEGIN_COLLECTION,
    TAG_INTEGER,
    TAG_KEYWORD,
    IppClient,
    IppCollection,
)
from hp_printer_mcp.media import MediaSize, resolve_media, resolve_media_type
from hp_printer_mcp.print_options import PrintSettings

_CAPS_ATTRIBUTES = [
    "document-format-supported",
    "media-supported",
    "media-type-supported",
    "media-source-supported",
    "media-ready",
    "media-col-default",
    "media-col-database",
    "media-top-margin-supported",
    "media-bottom-margin-supported",
    "media-left-margin-supported",
    "media-right-margin-supported",
    "sides-supported",
    "print-color-mode-supported",
    "print-quality-supported",
    "printer-resolution-supported",
    "pwg-raster-document-type-supported",
    "pwg-raster-document-sheet-back",
    "pwg-raster-document-resolution-supported",
    "print-scaling-supported",
    "copies-supported",
    "orientation-requested-supported",
]

_SIDES = {
    "none": "one-sided",
    "long_edge": "two-sided-long-edge",
    "short_edge": "two-sided-short-edge",
}
_QUALITY = {"draft": 3, "normal": 4, "high": 5, "best": 5}


@dataclass
class PrinterCaps:
    document_formats: list[str] = field(default_factory=list)
    media_supported: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    media_sources: list[str] = field(default_factory=list)
    media_ready: list[str] = field(default_factory=list)
    margin_top: list[int] = field(default_factory=list)
    margin_bottom: list[int] = field(default_factory=list)
    margin_left: list[int] = field(default_factory=list)
    margin_right: list[int] = field(default_factory=list)
    default_margins: tuple[int, int, int, int] | None = None
    media_col_database: list[dict[str, Any]] = field(default_factory=list)
    sides: list[str] = field(default_factory=list)
    color_modes: list[str] = field(default_factory=list)
    qualities: list[int] = field(default_factory=list)
    printer_resolutions: list[tuple[int, int, int]] = field(default_factory=list)
    pwg_resolutions: list[tuple[int, int, int]] = field(default_factory=list)
    pwg_types: list[str] = field(default_factory=list)
    sheet_back: str | None = None
    print_scaling: list[str] = field(default_factory=list)
    copies_supported: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class PrintTicket:
    media_name: str
    media_keyword: str
    x: int
    y: int
    media_type_name: str
    media_type: str
    margins: tuple[int, int, int, int]
    borderless: bool
    sides: str
    copies: int
    color_mode: str
    quality: int
    dpi: int
    pwg_type: str
    sheet_back: str | None
    print_scaling: str | None
    document_format: str
    media_col: IppCollection
    warnings: tuple[str, ...]


def fetch_printer_caps(ipp: IppClient) -> PrinterCaps:
    response = ipp.get_printer_attributes(_CAPS_ATTRIBUTES)
    return parse_printer_caps(response.attributes)


def parse_printer_caps(attributes: dict[str, list[Any]]) -> PrinterCaps:
    default_col = _first_dict(attributes.get("media-col-default"))
    database = [item for item in (attributes.get("media-col-database") or []) if isinstance(item, dict)]
    if not database and isinstance(default_col, dict):
        pass
    return PrinterCaps(
        document_formats=_strings(attributes.get("document-format-supported")),
        media_supported=_strings(attributes.get("media-supported")),
        media_types=_strings(attributes.get("media-type-supported")),
        media_sources=_strings(attributes.get("media-source-supported")),
        media_ready=_strings(attributes.get("media-ready")),
        margin_top=_ints(attributes.get("media-top-margin-supported")),
        margin_bottom=_ints(attributes.get("media-bottom-margin-supported")),
        margin_left=_ints(attributes.get("media-left-margin-supported")),
        margin_right=_ints(attributes.get("media-right-margin-supported")),
        default_margins=_margins_of(default_col) if default_col else None,
        media_col_database=database,
        sides=_strings(attributes.get("sides-supported")),
        color_modes=_strings(attributes.get("print-color-mode-supported")),
        qualities=_ints(attributes.get("print-quality-supported")),
        printer_resolutions=_resolutions(attributes.get("printer-resolution-supported")),
        pwg_resolutions=_resolutions(attributes.get("pwg-raster-document-resolution-supported")),
        pwg_types=_strings(attributes.get("pwg-raster-document-type-supported")),
        sheet_back=_first_str(attributes.get("pwg-raster-document-sheet-back")),
        print_scaling=_strings(attributes.get("print-scaling-supported")),
        copies_supported=list(attributes.get("copies-supported") or []),
    )


def choose_raster_dpi(caps: PrinterCaps) -> int:
    """300 dpi when the printer's PWG raster resolutions include it."""
    pool = caps.pwg_resolutions or caps.printer_resolutions
    dpis = [x for x, y, units in pool if x == y and units == 3 and x > 0]
    if not dpis:
        return 300
    if 300 in dpis:
        return 300
    return min(dpis, key=lambda value: (abs(value - 300), value))


def choose_document_format(caps: PrinterCaps, *, source_suffix: str) -> str:
    formats = {item.lower() for item in caps.document_formats}
    if not formats:
        raise ValueError("Printer did not report document-format-supported")
    if source_suffix == ".pdf" and "application/pdf" in formats:
        return "application/pdf"
    if "image/pwg-raster" in formats:
        return "image/pwg-raster"
    if "image/jpeg" in formats:
        return "image/jpeg"
    listed = ", ".join(caps.document_formats)
    raise ValueError(f"No usable document format. Printer supports: {listed}")


def resolve_print_ticket(
    settings: PrintSettings,
    caps: PrinterCaps,
    *,
    source_suffix: str,
) -> PrintTicket:
    warnings: list[str] = []
    media = resolve_media(settings.paper)
    _require_member(
        media.keyword,
        caps.media_supported,
        label=f"paper {settings.paper!r} ({media.keyword})",
        noun="media size",
    )
    type_name, media_type = resolve_media_type(settings.paper_type)
    _require_member(
        media_type,
        caps.media_types,
        label=f"paper_type {settings.paper_type!r} ({media_type})",
        noun="media type",
    )
    sides = _SIDES[settings.duplex]
    _require_member(sides, caps.sides, label=f"duplex {settings.duplex!r}", noun="sides value")
    _require_member(
        settings.color,
        caps.color_modes,
        label=f"color {settings.color!r}",
        noun="print-color-mode",
    )
    quality = _QUALITY[settings.quality]
    if caps.qualities and quality not in caps.qualities:
        raise ValueError(
            f"quality {settings.quality!r} is not supported. "
            f"Printer print-quality values: {', '.join(str(item) for item in caps.qualities)}"
        )
    _require_copies(settings.copies, caps.copies_supported)
    if caps.media_ready and media.keyword not in caps.media_ready:
        ready = ", ".join(caps.media_ready)
        warnings.append(f"Input tray reports {ready}, not {media.keyword}.")

    document_format = choose_document_format(caps, source_suffix=source_suffix.lower())
    if document_format == "image/jpeg" and settings.duplex != "none":
        warnings.append(
            "Printer has no image/pwg-raster; duplex is sent on each single-page JPEG "
            "and will not print on the back."
        )
    if document_format == "image/jpeg" and settings.copies > 1:
        warnings.append(
            "Printer has no image/pwg-raster; copies are repeated per page and will not collate."
        )

    margins = _select_margins(caps, media, media_type, borderless=settings.borderless)
    dpi = choose_raster_dpi(caps)
    pwg_type = _choose_pwg_type(caps, settings.color)
    scaling = "none" if "none" in caps.print_scaling else None
    if document_format == "image/pwg-raster" and scaling is None and caps.print_scaling:
        warnings.append(
            "Printer does not advertise print-scaling=none; it may rescale the raster."
        )
    media_col = _build_media_col(
        media,
        media_type=media_type,
        margins=margins,
        source="main" if "main" in caps.media_sources else None,
    )
    return PrintTicket(
        media_name=media.name,
        media_keyword=media.keyword,
        x=media.x,
        y=media.y,
        media_type_name=type_name,
        media_type=media_type,
        margins=margins,
        borderless=settings.borderless,
        sides=sides,
        copies=settings.copies,
        color_mode=settings.color,
        quality=quality,
        dpi=dpi,
        pwg_type=pwg_type,
        sheet_back=caps.sheet_back,
        print_scaling=scaling,
        document_format=document_format,
        media_col=media_col,
        warnings=tuple(warnings),
    )


def _build_media_col(
    media: MediaSize,
    *,
    media_type: str,
    margins: tuple[int, int, int, int],
    source: str | None,
) -> IppCollection:
    top, bottom, left, right = margins
    size = IppCollection(
        members=(
            (TAG_INTEGER, "x-dimension", media.x),
            (TAG_INTEGER, "y-dimension", media.y),
        )
    )
    members: list[tuple[Any, ...]] = [
        (TAG_BEGIN_COLLECTION, "media-size", size),
        (TAG_INTEGER, "media-top-margin", top),
        (TAG_INTEGER, "media-bottom-margin", bottom),
        (TAG_INTEGER, "media-left-margin", left),
        (TAG_INTEGER, "media-right-margin", right),
        (TAG_KEYWORD, "media-type", media_type),
    ]
    if source:
        members.append((TAG_KEYWORD, "media-source", source))
    return IppCollection(members=tuple(members))


def _select_margins(
    caps: PrinterCaps,
    media: MediaSize,
    media_type: str,
    *,
    borderless: bool,
) -> tuple[int, int, int, int]:
    wanted = (0, 0, 0, 0) if borderless else _bordered_margins(caps)
    sized = [
        entry
        for entry in caps.media_col_database
        if _size_of(entry) == (media.x, media.y)
    ]
    if sized:
        matched = [
            entry
            for entry in sized
            if _margins_of(entry) == wanted and _type_of(entry) in {None, media_type}
        ]
        has_this_type = any(_type_of(entry) == media_type for entry in sized)
        type_match = [entry for entry in matched if _type_of(entry) == media_type]
        if type_match or (matched and not has_this_type):
            return wanted
        if borderless:
            zero_types = sorted(
                {
                    str(_type_of(entry))
                    for entry in sized
                    if _margins_of(entry) == (0, 0, 0, 0) and _type_of(entry)
                }
            )
            if zero_types:
                raise ValueError(
                    f"borderless {media.name} is not available for {media_type}. "
                    f"Borderless media types for this size: {', '.join(zero_types)}"
                )
            raise ValueError(f"borderless is not available for {media.name}")
    if borderless and not _margin_allowed(caps, 0):
        raise ValueError("This printer does not support borderless (0 mm margins)")
    if not borderless and not _margins_allowed(caps, wanted):
        raise ValueError(f"Margins {wanted} are not supported by this printer")
    return wanted


def _bordered_margins(caps: PrinterCaps) -> tuple[int, int, int, int]:
    if caps.default_margins and any(value != 0 for value in caps.default_margins):
        return caps.default_margins
    edges = (caps.margin_top, caps.margin_bottom, caps.margin_left, caps.margin_right)
    picked: list[int] = []
    for values in edges:
        nonzero = [value for value in values if value != 0]
        if nonzero:
            picked.append(nonzero[0])
        elif values:
            picked.append(values[0])
        else:
            picked.append(296)
    return (picked[0], picked[1], picked[2], picked[3])


def _margin_allowed(caps: PrinterCaps, margin: int) -> bool:
    lists = (caps.margin_top, caps.margin_bottom, caps.margin_left, caps.margin_right)
    if not any(lists):
        return True
    return all((not values) or margin in values for values in lists)


def _margins_allowed(caps: PrinterCaps, margins: tuple[int, int, int, int]) -> bool:
    lists = (caps.margin_top, caps.margin_bottom, caps.margin_left, caps.margin_right)
    if not any(lists):
        return True
    return all((not values) or margin in values for values, margin in zip(lists, margins))


def _choose_pwg_type(caps: PrinterCaps, color_mode: str) -> str:
    types = set(caps.pwg_types)
    if color_mode == "monochrome" and (not types or "sgray_8" in types):
        return "sgray_8"
    if not types or "srgb_8" in types:
        return "srgb_8"
    raise ValueError(
        "Printer does not support srgb_8 PWG raster. "
        f"pwg-raster-document-type-supported: {', '.join(caps.pwg_types)}"
    )


def _require_member(value: str, supported: list[str], *, label: str, noun: str) -> None:
    if not supported or value in supported:
        return
    shown = ", ".join(supported)
    raise ValueError(f"{label} is not a supported {noun}. Printer supports: {shown}")


def _require_copies(copies: int, supported: list[Any]) -> None:
    if copies < 1:
        raise ValueError("copies must be >= 1")
    if not supported:
        return
    for item in supported:
        if isinstance(item, tuple) and len(item) == 2 and all(isinstance(part, int) for part in item):
            low, high = item
            if low <= copies <= high:
                return
            raise ValueError(f"copies must be between {low} and {high}")
        if item == copies:
            return
    raise ValueError(f"copies {copies} is outside copies-supported {supported}")


def _strings(values: list[Any] | None) -> list[str]:
    return [str(item) for item in values or [] if isinstance(item, str) and item]


def _ints(values: list[Any] | None) -> list[int]:
    found: list[int] = []
    for item in values or []:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            found.append(item)
    return found


def _resolutions(values: list[Any] | None) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    for item in values or []:
        if isinstance(item, tuple) and len(item) == 3 and all(isinstance(part, int) for part in item):
            found.append((int(item[0]), int(item[1]), int(item[2])))
    return found


def _first_str(values: list[Any] | None) -> str | None:
    for item in values or []:
        if isinstance(item, str) and item:
            return item
    return None


def _first_dict(values: list[Any] | None) -> dict[str, Any] | None:
    for item in values or []:
        if isinstance(item, dict):
            return item
    return None


def _size_of(entry: dict[str, Any]) -> tuple[int, int] | None:
    size = entry.get("media-size")
    if not isinstance(size, dict):
        return None
    x = size.get("x-dimension")
    y = size.get("y-dimension")
    if isinstance(x, int) and not isinstance(x, bool) and isinstance(y, int) and not isinstance(y, bool):
        return (x, y)
    return None


def _type_of(entry: dict[str, Any]) -> str | None:
    value = entry.get("media-type")
    if isinstance(value, str):
        return value
    return None


def _margins_of(entry: dict[str, Any]) -> tuple[int, int, int, int] | None:
    try:
        return (
            int(entry["media-top-margin"]),
            int(entry["media-bottom-margin"]),
            int(entry["media-left-margin"]),
            int(entry["media-right-margin"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
