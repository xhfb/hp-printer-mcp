"""Friendly paper and media-type names for the Smart Tank 750.

Dimensions are parsed from the IPP self-describing keyword (PWG 5101.1).
Hundredths of a millimetre match the ``media-size`` units used in ``media-col``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MM_SIZE = re.compile(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm\Z")
_IN_SIZE = re.compile(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)in\Z")

# Compact user token (uppercase, no spaces or hyphens) -> IPP media keyword.
MEDIA_ALIASES: dict[str, str] = {
    "A4": "iso_a4_210x297mm",
    "A5": "iso_a5_148x210mm",
    "A6": "iso_a6_105x148mm",
    "B5": "iso_b5_176x250mm",
    "ISOB5": "iso_b5_176x250mm",
    "JISB5": "jis_b5_182x257mm",
    "B5JIS": "jis_b5_182x257mm",
    "LETTER": "na_letter_8.5x11in",
    "LEGAL": "na_legal_8.5x14in",
    "EXECUTIVE": "na_executive_7.25x10.5in",
    "8X10": "na_govt-letter_8x10in",
    "GOVTLETTER": "na_govt-letter_8x10in",
    "STATEMENT": "na_invoice_5.5x8.5in",
    "INVOICE": "na_invoice_5.5x8.5in",
    "HAGAKI": "jpn_hagaki_100x148mm",
    "OUFUKU": "jpn_oufuku_148x200mm",
    "4X6": "na_index-4x6_4x6in",
    "PHOTO4X6": "na_index-4x6_4x6in",
    "10X15": "om_small-photo_100x150mm",
    "10X15CM": "om_small-photo_100x150mm",
    "PHOTO10X15": "om_small-photo_100x150mm",
    "5X7": "na_5x7_5x7in",
    "5X8": "na_index-5x8_5x8in",
    "L": "oe_photo-l_3.5x5in",
    "PHOTOL": "oe_photo-l_3.5x5in",
    "3.5X5": "oe_photo-l_3.5x5in",
    "35X5": "oe_photo-l_3.5x5in",
    "2L": "jpn_photo-2l_127x177.8mm",
    "PHOTO2L": "jpn_photo-2l_127x177.8mm",
    "ENV10": "na_number-10_4.125x9.5in",
    "NUMBER10": "na_number-10_4.125x9.5in",
    "NO10": "na_number-10_4.125x9.5in",
    "#10": "na_number-10_4.125x9.5in",
    "DL": "iso_dl_110x220mm",
    "C6": "iso_c6_114x162mm",
    "CHOU3": "jpn_chou3_120x235mm",
    "CHOU4": "jpn_chou4_90x205mm",
    "FOOLSCAP": "na_foolscap_8.5x13in",
}

# public name, IPP media-type keyword
_PAPER_TYPES: dict[str, tuple[str, str]] = {
    "plain": ("plain", "stationery"),
    "stationery": ("plain", "stationery"),
    "lightweight": ("lightweight", "stationery-lightweight"),
    "light": ("lightweight", "stationery-lightweight"),
    "thin": ("lightweight", "stationery-lightweight"),
    "stationery-lightweight": ("lightweight", "stationery-lightweight"),
    "photo": ("photo", "photographic-glossy"),
    "glossy": ("photo", "photographic-glossy"),
    "photo-glossy": ("photo", "photographic-glossy"),
    "photographic-glossy": ("photo", "photographic-glossy"),
    "photo-inkjet": ("photo-inkjet", "com.hp-photographic-inkjet"),
    "hp-photo": ("photo-inkjet", "com.hp-photographic-inkjet"),
    "inkjet-photo": ("photo-inkjet", "com.hp-photographic-inkjet"),
    "com.hp-photographic-inkjet": ("photo-inkjet", "com.hp-photographic-inkjet"),
    "specialty-glossy": ("specialty-glossy", "com.hp-specialty-glossy"),
    "premium-glossy": ("specialty-glossy", "com.hp-specialty-glossy"),
    "com.hp-specialty-glossy": ("specialty-glossy", "com.hp-specialty-glossy"),
    "specialty-glossy-inkjet": (
        "specialty-glossy-inkjet",
        "com.hp-specialty-glossy-inkjet",
    ),
    "com.hp-specialty-glossy-inkjet": (
        "specialty-glossy-inkjet",
        "com.hp-specialty-glossy-inkjet",
    ),
    "matte": ("matte", "com.hp-matte-presentation"),
    "presentation": ("matte", "com.hp-matte-presentation"),
    "matte-presentation": ("matte", "com.hp-matte-presentation"),
    "com.hp-matte-presentation": ("matte", "com.hp-matte-presentation"),
    "brochure": ("brochure", "com.hp-matte-brochure"),
    "matte-brochure": ("brochure", "com.hp-matte-brochure"),
    "com.hp-matte-brochure": ("brochure", "com.hp-matte-brochure"),
    "matte-inkjet": ("matte-inkjet", "com.hp-matte-inkjet"),
    "com.hp-matte-inkjet": ("matte-inkjet", "com.hp-matte-inkjet"),
}

_FRIENDLY_BY_KEYWORD: dict[str, str] = {}
for _token, _keyword in MEDIA_ALIASES.items():
    _FRIENDLY_BY_KEYWORD.setdefault(_keyword, _token)


@dataclass(frozen=True)
class MediaSize:
    name: str
    keyword: str
    x: int  # portrait width, hundredths of a millimetre
    y: int  # portrait height, hundredths of a millimetre

    def pixel_size(self, dpi: int) -> tuple[int, int]:
        if dpi < 1:
            raise ValueError("dpi must be >= 1")
        return (self.x * dpi // 2540, self.y * dpi // 2540)


def _compact(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("-", "").replace("_", "")


def _hundredths_from_keyword(keyword: str) -> tuple[int, int]:
    token = keyword.rsplit("_", 1)[-1]
    mm = _MM_SIZE.fullmatch(token)
    if mm:
        return (int(round(float(mm.group(1)) * 100)), int(round(float(mm.group(2)) * 100)))
    inches = _IN_SIZE.fullmatch(token)
    if inches:
        # Truncate, do not round. 4.125 in is 10477.5 hundredths of a millimetre;
        # this Smart Tank's media-col-database stores 10477, and every other
        # advertised inch size lands on an integer.
        return (
            int(float(inches.group(1)) * 2540),
            int(float(inches.group(2)) * 2540),
        )
    raise ValueError(f"Cannot read dimensions from media keyword {keyword!r}")


def known_paper_names() -> list[str]:
    seen: list[str] = []
    for name in _FRIENDLY_BY_KEYWORD.values():
        if name not in seen:
            seen.append(name)
    return sorted(seen)


def resolve_media(paper: str) -> MediaSize:
    raw = paper.strip()
    if not raw:
        raise ValueError("paper is required")
    compact = _compact(raw)
    # Keep a dotted alias such as 3.5x5 from being stripped to 35x5 before lookup.
    dotted = raw.strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    keyword = MEDIA_ALIASES.get(dotted) or MEDIA_ALIASES.get(compact)
    if keyword is None:
        lowered = raw.lower()
        if lowered.startswith("custom_"):
            raise ValueError(
                "Custom media sizes are not supported. "
                f"Use one of: {', '.join(known_paper_names())}"
            )
        if "_" in lowered and (_MM_SIZE.search(lowered) or _IN_SIZE.search(lowered)):
            keyword = lowered
        else:
            raise ValueError(
                f"Unknown paper {paper!r}. Use one of: {', '.join(known_paper_names())}"
            )
    width, height = _hundredths_from_keyword(keyword)
    name = _FRIENDLY_BY_KEYWORD.get(keyword, keyword)
    return MediaSize(name=name, keyword=keyword, x=width, y=height)


def known_paper_type_names() -> list[str]:
    names: list[str] = []
    for public, _keyword in _PAPER_TYPES.values():
        if public not in names:
            names.append(public)
    return sorted(names)


def resolve_media_type(paper_type: str) -> tuple[str, str]:
    """Return ``(public_name, ipp_media_type)``."""
    key = paper_type.strip().lower().replace(" ", "-").replace("_", "-")
    if not key:
        raise ValueError("paper_type is required")
    found = _PAPER_TYPES.get(key)
    if found:
        return found
    if key.startswith("com."):
        return key, key
    names = ", ".join(known_paper_type_names())
    raise ValueError(
        f"Unknown paper_type {paper_type!r}. Use one of: {names}. "
        "Vendor keywords such as com.hp-matte-inkjet are also accepted."
    )
