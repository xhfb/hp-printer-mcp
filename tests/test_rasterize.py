from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from hp_printer_mcp.rasterize import _load_text_font, _render_text_pages, rasterize_to_jpegs


def test_rasterize_txt(tmp_path: Path):
    src = tmp_path / "note.txt"
    src.write_text("MCP IPP print test\n第二行", encoding="utf-8")
    pages = rasterize_to_jpegs(src, paper="A4", color="monochrome")
    assert len(pages) >= 1
    assert pages[0][:2] == b"\xff\xd8"  # JPEG SOI


def test_cjk_font_loads_and_renders():
    font = _load_text_font(36)
    # FreeType fonts expose getmask; default bitmap font is last-resort only.
    pages = _render_text_pages(
        "中文打印测试 ABC",
        paper="A4",
        orientation="portrait",
        monochrome=True,
    )
    assert len(pages) == 1
    # Non-white pixels should exist (text was drawn)
    extrema = pages[0].convert("L").getextrema()
    assert extrema[0] < 250
