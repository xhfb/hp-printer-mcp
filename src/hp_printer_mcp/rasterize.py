from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hp_printer_mcp.print_options import PAPER_SIZES, parse_page_range

# Portrait pixels at ~150 DPI for common paper sizes (approx).
PAPER_PX: dict[str, tuple[int, int]] = {
    "A3": (1754, 2480),
    "A4": (1240, 1754),
    "A5": (874, 1240),
    "B4": (1476, 2085),
    "B5": (1039, 1476),
    "LETTER": (1275, 1650),
    "LEGAL": (1275, 2100),
    "TABLOID": (1650, 2550),
    "EXECUTIVE": (1088, 1575),
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}
TEXT_EXTENSIONS = {".txt", ".log", ".md", ".csv"}

# Prefer CJK-capable fonts so Chinese does not render as tofu (□).
_FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\arialuni.ttf",
    # Linux / Pi
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_text_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    env_font = os.getenv("HP_PRINT_FONT", "").strip()
    candidates = ([env_font] if env_font else []) + _FONT_CANDIDATES
    for path in candidates:
        if not path:
            continue
        try:
            # index=0 for TTC collections
            return ImageFont.truetype(path, size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2] - bbox[0])


def _wrap_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    if not line:
        return [""]
    # Fast path when whole line fits
    if _text_width(draw, line, font) <= max_width:
        return [line]

    chunks: list[str] = []
    current = ""
    for ch in line:
        trial = current + ch
        if current and _text_width(draw, trial, font) > max_width:
            chunks.append(current)
            current = ch
        else:
            current = trial
    if current:
        chunks.append(current)
    return chunks or [""]


def _page_size(paper: str, orientation: str) -> tuple[int, int]:
    key = paper.strip().upper().replace(" ", "")
    if key not in PAPER_PX:
        if key not in PAPER_SIZES:
            raise ValueError(f"Unsupported paper size: {paper}")
        width, height = 1240, 1754
    else:
        width, height = PAPER_PX[key]
    if orientation.strip().lower() == "landscape":
        width, height = height, width
    return width, height


def _to_rgb(img: Image.Image, *, monochrome: bool) -> Image.Image:
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if monochrome:
        img = img.convert("L").convert("RGB")
    return img


def _fit_on_page(img: Image.Image, page_size: tuple[int, int]) -> Image.Image:
    page = Image.new("RGB", page_size, "white")
    fitted = img.copy()
    fitted.thumbnail(page_size, Image.Resampling.LANCZOS)
    x = (page_size[0] - fitted.width) // 2
    y = (page_size[1] - fitted.height) // 2
    page.paste(fitted, (x, y))
    return page


def _render_text_pages(
    text: str,
    *,
    paper: str,
    orientation: str,
    monochrome: bool,
) -> list[Image.Image]:
    width, height = _page_size(paper, orientation)
    margin = 72  # ~0.48" at 150 DPI
    # ~12pt body text at 150 DPI; readable on A4 hardcopy
    font_size = int(os.getenv("HP_PRINT_FONT_SIZE", "36"))
    font = _load_text_font(font_size)
    # Measure real glyph metrics for spacing
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10), "white"))
    sample_bbox = probe.textbbox((0, 0), "汉字Ag", font=font)
    glyph_h = max(font_size, sample_bbox[3] - sample_bbox[1])
    line_height = int(glyph_h * 1.45)
    max_width = width - 2 * margin

    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    wrapped: list[str] = []
    for line in raw_lines:
        wrapped.extend(_wrap_line(probe, line, font, max_width))

    lines_per_page = max(1, (height - 2 * margin) // line_height)
    pages: list[Image.Image] = []
    for start in range(0, max(1, len(wrapped)), lines_per_page):
        chunk = wrapped[start : start + lines_per_page]
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        y = margin
        fill = (0, 0, 0)
        for line in chunk:
            draw.text((margin, y), line, fill=fill, font=font)
            y += line_height
        pages.append(_to_rgb(img, monochrome=monochrome))
    return pages


def _render_pdf_pages(
    path: Path,
    *,
    paper: str,
    orientation: str,
    monochrome: bool,
    page_range: str,
) -> list[Image.Image]:
    import fitz

    doc = fitz.open(path)
    try:
        indices = parse_page_range(page_range, total_pages=doc.page_count)
        page_size = _page_size(paper, orientation)
        pages: list[Image.Image] = []
        for idx in indices:
            page = doc.load_page(idx)
            # ~150 DPI
            pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img = _to_rgb(img, monochrome=monochrome)
            pages.append(_fit_on_page(img, page_size))
        return pages
    finally:
        doc.close()


def _render_image_pages(
    path: Path,
    *,
    paper: str,
    orientation: str,
    monochrome: bool,
) -> list[Image.Image]:
    with Image.open(path) as img:
        converted = _to_rgb(img, monochrome=monochrome)
        return [_fit_on_page(converted, _page_size(paper, orientation))]


def rasterize_to_jpegs(
    path: Path,
    *,
    paper: str = "A4",
    orientation: str = "portrait",
    color: str = "color",
    page_range: str = "all",
    quality: int = 85,
) -> list[bytes]:
    """Convert a printable file into one JPEG byte blob per page."""
    suffix = path.suffix.lower()
    monochrome = color.strip().lower() == "monochrome"

    if suffix in PDF_EXTENSIONS:
        images = _render_pdf_pages(
            path,
            paper=paper,
            orientation=orientation,
            monochrome=monochrome,
            page_range=page_range,
        )
    elif suffix in IMAGE_EXTENSIONS:
        images = _render_image_pages(
            path, paper=paper, orientation=orientation, monochrome=monochrome
        )
    elif suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        images = _render_text_pages(
            text, paper=paper, orientation=orientation, monochrome=monochrome
        )
    else:
        raise ValueError(
            f"Unsupported file type for IPP rasterize: {suffix}. "
            "Convert Office documents to PDF/TXT/image first, or use a host with converters."
        )

    result: list[bytes] = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        result.append(buf.getvalue())
        img.close()
    return result
