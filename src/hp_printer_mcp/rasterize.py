from __future__ import annotations

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
    margin = 60
    line_height = 28
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except OSError:
            font = ImageFont.load_default()

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    max_chars = max(20, (width - 2 * margin) // 10)
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        while len(line) > max_chars:
            wrapped.append(line[:max_chars])
            line = line[max_chars:]
        wrapped.append(line)

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
