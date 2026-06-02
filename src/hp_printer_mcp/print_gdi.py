from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

from hp_printer_mcp.print_options import PrintSettings, get_printer_devmode, parse_page_range


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Printing is only supported on Windows")


def _win32ui():
    _require_windows()
    try:
        import win32con
        import win32gui
        import win32ui
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required for printing on Windows. Install with: pip install pywin32"
        ) from exc
    return win32con, win32gui, win32ui


def _create_printer_dc(printer_name: str, devmode: Any):
    _, win32gui, win32ui = _win32ui()
    hdc = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
    if not hdc:
        raise RuntimeError(f"Could not create printer DC for {printer_name!r}")
    return win32ui.CreateDCFromHandle(hdc)


def _fit_rect(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    if src_w <= 0 or src_h <= 0:
        return 0, 0, dst_w, dst_h
    scale = min(dst_w / src_w, dst_h / src_h)
    w = max(1, int(src_w * scale))
    h = max(1, int(src_h * scale))
    x = (dst_w - w) // 2
    y = (dst_h - h) // 2
    return x, y, w, h


def _draw_pil_image(dc, image, *, dst_x: int, dst_y: int, dst_w: int, dst_h: int) -> None:
    from PIL import ImageWin

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    dib = ImageWin.Dib(image)
    dib.draw(dc.GetHandleOutput(), (dst_x, dst_y, dst_x + dst_w, dst_y + dst_h))


def _render_pdf_page(page: Any, target_width: int) -> Any:
    import fitz

    zoom = max(target_width / page.rect.width, 0.1)
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    from PIL import Image

    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def print_pdf_gdi(
    path: Path,
    printer_name: str,
    settings: PrintSettings,
) -> None:
    import fitz

    devmode = get_printer_devmode(printer_name, settings)
    doc = fitz.open(str(path))
    try:
        page_indices = parse_page_range(settings.page_range, total_pages=doc.page_count)
        if not page_indices:
            raise ValueError("No pages selected for printing")

        win32con, _, _ = _win32ui()
        dc = _create_printer_dc(printer_name, devmode)
        dc.StartDoc(str(path.name))
        try:
            printable_w = dc.GetDeviceCaps(win32con.HORZRES)
            printable_h = dc.GetDeviceCaps(win32con.VERTRES)

            for page_idx in page_indices:
                dc.StartPage()
                image = _render_pdf_page(doc[page_idx], printable_w)
                x, y, w, h = _fit_rect(image.width, image.height, printable_w, printable_h)
                _draw_pil_image(dc, image, dst_x=x, dst_y=y, dst_w=w, dst_h=h)
                dc.EndPage()
        finally:
            dc.EndDoc()
    finally:
        doc.close()


def print_image_gdi(
    path: Path,
    printer_name: str,
    settings: PrintSettings,
) -> None:
    from PIL import Image

    devmode = get_printer_devmode(printer_name, settings)
    image = Image.open(path)
    win32con, _, _ = _win32ui()
    dc = _create_printer_dc(printer_name, devmode)
    dc.StartDoc(str(path.name))
    try:
        printable_w = dc.GetDeviceCaps(win32con.HORZRES)
        printable_h = dc.GetDeviceCaps(win32con.VERTRES)
        dc.StartPage()
        x, y, w, h = _fit_rect(image.width, image.height, printable_w, printable_h)
        _draw_pil_image(dc, image, dst_x=x, dst_y=y, dst_w=w, dst_h=h)
        dc.EndPage()
    finally:
        dc.EndDoc()


def print_text_gdi(
    path: Path,
    printer_name: str,
    settings: PrintSettings,
) -> None:
    text = path.read_text(encoding="utf-8")
    devmode = get_printer_devmode(printer_name, settings)
    win32con, _, _ = _win32ui()

    dc = _create_printer_dc(printer_name, devmode)
    dc.StartDoc(str(path.name))
    try:
        printable_w = dc.GetDeviceCaps(win32con.HORZRES)
        printable_h = dc.GetDeviceCaps(win32con.VERTRES)
        margin = dc.GetDeviceCaps(win32con.LOGPIXELSX) // 4
        line_height = dc.GetTextExtent("Ag")[1] + 4
        chars_per_line = max(20, (printable_w - margin * 2) // dc.GetTextExtent("M")[0])

        y = margin
        dc.StartPage()
        for paragraph in text.splitlines() or [""]:
            wrapped = textwrap.wrap(paragraph, width=chars_per_line) or [""]
            for line in wrapped:
                if y + line_height > printable_h - margin:
                    dc.EndPage()
                    dc.StartPage()
                    y = margin
                dc.TextOut(margin, y, line)
                y += line_height
        dc.EndPage()
    finally:
        dc.EndDoc()


def print_with_gdi(
    path: Path,
    printer_name: str,
    settings: PrintSettings,
) -> None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        print_pdf_gdi(path, printer_name, settings)
        return
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        print_image_gdi(path, printer_name, settings)
        return
    if suffix == ".txt":
        print_text_gdi(path, printer_name, settings)
        return
    raise ValueError(f"GDI print does not support {suffix}")
