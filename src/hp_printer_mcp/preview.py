"""Print preview for the agent. Same rasterizer as IPP print; no job is sent."""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hp_printer_mcp.config import Settings, fail, ok
from hp_printer_mcp.job_input import JobInputError, resolve_print_input
from hp_printer_mcp.print_options import normalize_print_settings
from hp_printer_mcp.rasterize import (
    PDF_EXTENSIONS,
    _draw_text_mixed,
    _load_text_fonts,
    _text_width_mixed,
    rasterize_document,
)

# Same 300 dpi the print path picks when the Smart Tank offers it.
RASTER_DPI = 300
# Bordered media-col on this Smart Tank: 296 hundredths of a millimetre (2.96 mm).
BORDERED_MARGINS = (296, 296, 296, 296)
VIEW_MAX_LONG_EDGE = 1500
VIEW_PAD = 16
CAPTION_HEIGHT = 48
MAX_PREVIEW_PAGES = 8
DEFAULT_PREVIEW_PAGES = 6
INLINE_PNG_LIMIT = 1_200_000
PREVIEW_KEEP = 20
COMBINED_MAX_HEIGHT = 7000
_INK_THRESHOLD = 250


@dataclass
class PreviewOutput:
    payload: dict[str, Any]
    images: list[tuple[bytes, str]] = field(default_factory=list)

    def as_tool_result(self) -> dict[str, Any] | list[Any]:
        """JSON first, then one image per preview page so the agent can see it."""
        if not self.images:
            return self.payload
        from mcp.server.fastmcp import Image as McpImage

        blocks: list[Any] = [self.payload]
        for data, fmt in self.images:
            blocks.append(McpImage(data=data, format=fmt))
        return blocks


def reading_margin_px(
    margins: tuple[int, int, int, int],
    *,
    orientation: str,
    dpi: int,
) -> tuple[int, int, int, int]:
    """Map physical-sheet margins into the reading-direction page.

    ``margins`` is ``(top, bottom, left, right)`` in hundredths of a millimetre
    on the portrait sheet the printer feeds. Landscape pages are composed wide
    and then rotated 90° counter-clockwise into that sheet.
    """
    top, bottom, left, right = (value * dpi // 2540 for value in margins)
    if orientation.strip().lower() == "landscape":
        # Feed top comes from the reading page's right edge, feed bottom from
        # its left, feed left from its top, feed right from its bottom.
        return (left, right, bottom, top)
    return (top, bottom, left, right)


def content_in_unprintable_margin(
    image: Image.Image, insets: tuple[int, int, int, int]
) -> bool:
    """True when any non-white pixel sits in the unprintable band."""
    top, bottom, left, right = insets
    if max(insets) <= 0:
        return False
    rgb = image.convert("RGB")
    width, height = rgb.size
    boxes: list[tuple[int, int, int, int]] = []
    if top > 0:
        boxes.append((0, 0, width, min(height, top)))
    if bottom > 0 and bottom < height:
        boxes.append((0, height - bottom, width, height))
    if left > 0:
        boxes.append((0, 0, min(width, left), height))
    if right > 0 and right < width:
        boxes.append((width - right, 0, width, height))
    for box in boxes:
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        extrema = rgb.crop(box).getextrema()
        if any(channel[0] < _INK_THRESHOLD for channel in extrema):
            return True
    return False


def _downscale(image: Image.Image, max_edge: int) -> Image.Image:
    width, height = image.size
    long_edge = max(width, height)
    if long_edge <= max_edge:
        return image.copy()
    scale = max_edge / long_edge
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _scale_insets(
    insets: tuple[int, int, int, int],
    src: tuple[int, int],
    dst: tuple[int, int],
) -> tuple[int, int, int, int]:
    sx = dst[0] / src[0]
    sy = dst[1] / src[1]
    top, bottom, left, right = insets
    return (
        int(round(top * sy)),
        int(round(bottom * sy)),
        int(round(left * sx)),
        int(round(right * sx)),
    )


def _dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: tuple[int, int, int],
    width: int,
    dash: int = 10,
    gap: int = 6,
) -> None:
    x0, y0 = start
    x1, y1 = end
    if x0 == x1:
        y = min(y0, y1)
        stop = max(y0, y1)
        while y < stop:
            y2 = min(stop, y + dash)
            draw.line((x0, y, x1, y2), fill=fill, width=width)
            y = y2 + gap
        return
    x = min(x0, x1)
    stop = max(x0, x1)
    while x < stop:
        x2 = min(stop, x + dash)
        draw.line((x, y0, x2, y1), fill=fill, width=width)
        x = x2 + gap


def _mark_margins(page: Image.Image, insets: tuple[int, int, int, int]) -> Image.Image:
    """Shade the unprintable band and dash the printable boundary."""
    top, bottom, left, right = insets
    marked = page.convert("RGBA")
    if max(insets) <= 0:
        return marked.convert("RGB")
    width, height = marked.size
    overlay = Image.new("RGBA", marked.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    wash = (210, 30, 30, 56)
    if top > 0:
        draw.rectangle((0, 0, width - 1, top - 1), fill=wash)
    if bottom > 0:
        draw.rectangle((0, height - bottom, width - 1, height - 1), fill=wash)
    if left > 0:
        draw.rectangle((0, 0, left - 1, height - 1), fill=wash)
    if right > 0:
        draw.rectangle((width - right, 0, width - 1, height - 1), fill=wash)
    marked = Image.alpha_composite(marked, overlay)
    rgb = marked.convert("RGB")
    boundary = ImageDraw.Draw(rgb)
    x0 = min(max(left, 0), width - 1)
    y0 = min(max(top, 0), height - 1)
    x1 = min(max(width - 1 - right, 0), width - 1)
    y1 = min(max(height - 1 - bottom, 0), height - 1)
    if x1 > x0 and y1 > y0:
        red = (180, 20, 20)
        _dashed_line(boundary, (x0, y0), (x1, y0), fill=red, width=2)
        _dashed_line(boundary, (x0, y1), (x1, y1), fill=red, width=2)
        _dashed_line(boundary, (x0, y0), (x0, y1), fill=red, width=2)
        _dashed_line(boundary, (x1, y0), (x1, y1), fill=red, width=2)
    return rgb


def _fit_caption(text: str, max_width: int) -> tuple[Any, Any, str]:
    candidates = [text]
    if "·" in text:
        candidates.append(text.split("·")[0].strip())
    for size in (24, 18, 14):
        cjk, latin = _load_text_fonts(size)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for candidate in candidates:
            if _text_width_mixed(probe, candidate, cjk, latin) <= max_width:
                return cjk, latin, candidate
    cjk, latin = _load_text_fonts(14)
    return cjk, latin, candidates[-1]


def _view_image(page: Image.Image, *, caption: str, insets: tuple[int, int, int, int], show_margins: bool) -> Image.Image:
    body = _mark_margins(page, insets) if show_margins else page.convert("RGB")
    canvas = Image.new(
        "RGB",
        (body.width + VIEW_PAD * 2, body.height + VIEW_PAD * 2 + CAPTION_HEIGHT),
        (232, 232, 232),
    )
    canvas.paste(body, (VIEW_PAD, VIEW_PAD))
    draw = ImageDraw.Draw(canvas)
    cjk, latin, shown = _fit_caption(caption, max(40, body.width))
    _draw_text_mixed(
        draw,
        (VIEW_PAD, VIEW_PAD + body.height + 10),
        shown,
        cjk=cjk,
        latin=latin,
        fill=(40, 40, 40),
    )
    body.close()
    return canvas


def _png_bytes(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _inline_from_png(png: bytes) -> tuple[bytes, str]:
    if len(png) <= INLINE_PNG_LIMIT:
        return png, "png"
    with Image.open(BytesIO(png)) as image:
        buf = BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "jpeg"


def _stack(views: list[Image.Image]) -> Image.Image:
    gap = 12
    width = max(image.width for image in views)
    height = sum(image.height for image in views) + gap * (len(views) - 1)
    sheet = Image.new("RGB", (width, height), (232, 232, 232))
    y = 0
    for image in views:
        x = (width - image.width) // 2
        sheet.paste(image, (x, y))
        y += image.height + gap
    if sheet.height > COMBINED_MAX_HEIGHT:
        scale = COMBINED_MAX_HEIGHT / sheet.height
        resized = sheet.resize(
            (max(1, round(sheet.width * scale)), COMBINED_MAX_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        sheet.close()
        return resized
    return sheet


def _prune_previews(root: Path) -> None:
    dirs = [path for path in root.iterdir() if path.is_dir()]
    now = time.time()
    for path in dirs:
        try:
            if path.stat().st_mtime < now - 86400:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue
    survivors = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in survivors[PREVIEW_KEEP - 1 :]:
        shutil.rmtree(path, ignore_errors=True)


def _prepare_preview_dir(settings: Settings) -> Path:
    root = settings.scan_output_dir.expanduser().resolve() / "preview"
    root.mkdir(parents=True, exist_ok=True)
    _prune_previews(root)
    folder = root / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder.mkdir()
    return folder


def _margin_hundredths(borderless: bool) -> tuple[int, int, int, int]:
    if borderless:
        return (0, 0, 0, 0)
    return BORDERED_MARGINS


def _mm(hundredths: int) -> str:
    return f"{hundredths / 100:.2f}"


def preview_print(
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
    max_pages: int = DEFAULT_PREVIEW_PAGES,
    show_margins: bool = True,
    printer_name: str | None = None,
) -> PreviewOutput:
    """Rasterize like ``hp_print_file`` and return reading-direction page images."""
    del printer_name
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
        return PreviewOutput(fail(str(exc)))

    if max_pages < 1:
        return PreviewOutput(fail("max_pages must be >= 1"))
    capped = min(max_pages, MAX_PREVIEW_PAGES)
    dpi = RASTER_DPI
    margins = _margin_hundredths(print_settings.borderless)
    full_insets = reading_margin_px(
        margins, orientation=print_settings.orientation, dpi=dpi
    )

    job_dir: Path | None = None
    pages: list[Image.Image] = []
    owned: list[Image.Image] = []
    preview_dir: Path | None = None
    try:
        source, job_dir = resolve_print_input(
            settings,
            file_path=file_path,
            content_base64=content_base64,
            filename=filename,
            url=url,
        )
        pages, total_pages = rasterize_document(
            source,
            paper=print_settings.paper,
            orientation=print_settings.orientation,
            color=print_settings.color,
            page_range=print_settings.page_range,
            dpi=dpi,
            max_pages=capped,
        )
        if not pages:
            return PreviewOutput(fail("Rasterizer produced no pages"))

        preview_dir = _prepare_preview_dir(settings)
        landscape = print_settings.orientation == "landscape"
        duplex_on = print_settings.duplex != "none"
        page_meta: list[dict[str, Any]] = []
        inline: list[tuple[bytes, str]] = []
        clipped: list[int] = []
        view_insets = (0, 0, 0, 0)

        for index, image in enumerate(pages, start=1):
            touches = content_in_unprintable_margin(image, full_insets)
            if touches:
                clipped.append(index)
            clean = _downscale(image, VIEW_MAX_LONG_EDGE)
            owned.append(clean)
            view_insets = _scale_insets(full_insets, image.size, clean.size)
            side = ""
            if duplex_on:
                side = "正面" if index % 2 == 1 else "背面"
            caption_bits = [f"第 {index}/{total_pages} 页"]
            if side:
                caption_bits.append(side)
            caption_bits.append(f"{print_settings.paper} {'横向' if landscape else '纵向'}")
            if show_margins and not print_settings.borderless:
                caption_bits.append("淡红边不会印出")
            view = _view_image(
                clean,
                caption=" · ".join(caption_bits),
                insets=view_insets,
                show_margins=show_margins and not print_settings.borderless,
            )
            owned.append(view)
            clean_path = preview_dir / f"page-{index:02d}.png"
            view_path = preview_dir / f"page-{index:02d}-view.png"
            clean_path.write_bytes(_png_bytes(clean))
            view_png = _png_bytes(view)
            view_path.write_bytes(view_png)
            inline.append(_inline_from_png(view_png))
            page_meta.append(
                {
                    "page": index,
                    "side": side or None,
                    "width_px": clean.width,
                    "height_px": clean.height,
                    "image_path": str(clean_path),
                    "view_image_path": str(view_path),
                    "content_in_unprintable_margin": touches,
                }
            )

        combined_path: str | None = None
        # ``owned`` alternates clean page, captioned view.
        view_images = owned[1::2]
        if len(view_images) > 1:
            combined = _stack(view_images)
            owned.append(combined)
            target = preview_dir / "combined-view.png"
            target.write_bytes(_png_bytes(combined))
            combined_path = str(target)

        notes, warnings = _messages(
            source_suffix=source.suffix.lower(),
            settings=print_settings,
            total_pages=total_pages,
            shown=len(page_meta),
            clipped=clipped,
            show_margins=show_margins,
            dpi=dpi,
        )
        top, bottom, left, right = margins
        data = {
            "printed": False,
            "sent_to_printer": False,
            "filename": source.name,
            "page_count": total_pages,
            "preview_page_count": len(page_meta),
            "truncated": len(page_meta) < total_pages,
            "raster_dpi": dpi,
            "view_max_long_edge": VIEW_MAX_LONG_EDGE,
            "view_pad_px": VIEW_PAD,
            "margins_hundredths_mm": {
                "top": top,
                "bottom": bottom,
                "left": left,
                "right": right,
            },
            "margins_mm": {
                "top": _mm(top),
                "bottom": _mm(bottom),
                "left": _mm(left),
                "right": _mm(right),
            },
            "margins_source": "hp-smart-tank-750",
            "unprintable_margin_px": {
                "top": view_insets[0],
                "bottom": view_insets[1],
                "left": view_insets[2],
                "right": view_insets[3],
            },
            "content_in_unprintable_margin": bool(clipped),
            "combined_view_path": combined_path,
            "pages": page_meta,
            "how_to_read": (
                "后面的图片与 pages 顺序一致，是阅读方向的 view。"
                "淡红边和红色虚线不会印出，用来标不可印边。"
                "image_path 是没有标记的成页。"
            ),
            "notes": notes,
            "warnings": warnings,
            **print_settings.to_dict(),
        }
        return PreviewOutput(ok(data), inline)
    except JobInputError as exc:
        if preview_dir is not None:
            shutil.rmtree(preview_dir, ignore_errors=True)
        return PreviewOutput(fail(str(exc)))
    except Exception as exc:
        if preview_dir is not None:
            shutil.rmtree(preview_dir, ignore_errors=True)
        return PreviewOutput(fail(f"Preview failed: {exc}"))
    finally:
        for image in pages:
            image.close()
        for image in owned:
            image.close()
        if job_dir is not None:
            shutil.rmtree(job_dir, ignore_errors=True)


def _messages(
    *,
    source_suffix: str,
    settings: Any,
    total_pages: int,
    shown: int,
    clipped: list[int],
    show_margins: bool,
    dpi: int,
) -> tuple[list[str], list[str]]:
    notes = [
        "没有送到打印机。",
        (
            f"按 {dpi} dpi 排版，和 hp_print_file 是同一套光栅；"
            f"长边超过 {VIEW_MAX_LONG_EDGE} 像素时缩小给 agent 看。"
        ),
        "warnings 为空只说明没有撞上不可印边，换行和疏密仍要看图。",
    ]
    warnings: list[str] = []
    if show_margins and not settings.borderless:
        top = _mm(BORDERED_MARGINS[0])
        notes.append(f"淡红边和红色虚线不会印出，标的是约 {top} mm 不可印边。")
    elif settings.borderless:
        notes.append("已按无边距预览，四边都可以有内容。")
    if settings.orientation == "landscape":
        notes.append("横版按阅读方向显示。出纸是竖向走纸，内容会逆时针转 90° 印到纸上。")
    if settings.duplex == "long_edge":
        notes.append("双面预览是翻开后的阅读方向。这台机器长边双面的背面光栅会再转 180°。")
    elif settings.duplex == "short_edge":
        notes.append("双面预览是翻开后的阅读方向。短边双面的背面不再多转 180°。")
    if settings.copies > 1:
        notes.append(f"只预览第 1 份，正式打印会重复 {settings.copies} 份。")
    if settings.duplex != "none" and total_pages % 2 == 1:
        if settings.copies > 1:
            notes.append(
                "页数是奇数。多份时，份与份之间会加一张空白背面，下一份从正面开始。预览不画这张空白。"
            )
        else:
            notes.append("页数是奇数，最后一张纸的背面是空白。预览不画这张空白。")
    if settings.color in {"auto", "auto-monochrome"}:
        notes.append("预览保留彩色像素；打印机可能按页面改成黑白。")
    if settings.quality != "normal":
        notes.append("quality 不改变预览图，只影响正式打印的质量档。")
    if shown < total_pages:
        warnings.append(f"将印出 {total_pages} 页，这里只生成前 {shown} 页。")
    if settings.page_range != "all" and source_suffix not in PDF_EXTENSIONS:
        warnings.append("page_range 只对 PDF 生效，这次预览包含全部页面。")
    if clipped:
        joined = "、".join(str(number) for number in clipped)
        warnings.append(f"第 {joined} 页有内容落在不可印边里，打印时可能被裁掉。")
    return notes, warnings
