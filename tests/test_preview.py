from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from mcp.server.fastmcp.server import _convert_to_content

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.media import resolve_media
from hp_printer_mcp.preview import (
    RASTER_DPI,
    VIEW_PAD,
    content_in_unprintable_margin,
    preview_print,
    reading_margin_px,
)
from hp_printer_mcp.rasterize import to_feed_orientation


@pytest.fixture
def fast_dpi(monkeypatch):
    monkeypatch.setattr("hp_printer_mcp.preview.RASTER_DPI", 96)


def _settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HP_PRINTER_HOST", "")
    monkeypatch.setenv("HP_SCAN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("HP_JOB_TMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("HP_PRINTER_ENV_FILE", str(tmp_path / "missing.env"))
    return load_settings()


def test_preview_raster_dpi_matches_print_default():
    assert RASTER_DPI == 300
    assert reading_margin_px((296, 296, 296, 296), orientation="portrait", dpi=300) == (
        34,
        34,
        34,
        34,
    )


def test_landscape_unprintable_band_matches_physical_sheet():
    physical = (10, 20, 30, 40)
    assert reading_margin_px(physical, orientation="landscape", dpi=2540) == (30, 40, 20, 10)
    assert reading_margin_px(physical, orientation="portrait", dpi=2540) == physical

    page = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(page)
    top, bottom, left, right = reading_margin_px(physical, orientation="landscape", dpi=2540)
    red = (255, 0, 0)
    draw.rectangle((0, 0, 199, top - 1), fill=red)
    draw.rectangle((0, 100 - bottom, 199, 99), fill=red)
    draw.rectangle((0, 0, left - 1, 99), fill=red)
    draw.rectangle((200 - right, 0, 199, 99), fill=red)
    feed = to_feed_orientation(page, "landscape")
    assert feed.size == (100, 200)
    assert feed.getpixel((50, 5)) == red
    assert feed.getpixel((50, 194)) == red
    assert feed.getpixel((5, 100)) == red
    assert feed.getpixel((94, 100)) == red
    assert feed.getpixel((50, 100)) == (255, 255, 255)


def test_text_preview_does_not_print_and_marks_margin(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "note.txt"
    src.write_text("打印预览 ABC\n第二行", encoding="utf-8")
    out = preview_print(settings, file_path=str(src), copies=2, orientation="portrait")
    assert out.payload["success"] is True
    data = out.payload["data"]
    assert data["printed"] is False
    assert data["sent_to_printer"] is False
    assert data["page_count"] == 1
    assert data["truncated"] is False
    assert data["content_in_unprintable_margin"] is False
    assert data["raster_dpi"] == 96
    assert data["margins_hundredths_mm"]["top"] == 296
    assert data["copies"] == 2
    assert any("第 1 份" in note for note in data["notes"])
    page = data["pages"][0]
    assert page["height_px"] > page["width_px"]
    assert Path(page["view_image_path"]).is_file()
    assert not any((tmp_path / "jobs").iterdir())

    clean = Image.open(page["image_path"])
    view = Image.open(page["view_image_path"])
    assert clean.getpixel((0, 0)) == (255, 255, 255)
    guide = view.getpixel((VIEW_PAD + 1, VIEW_PAD + 1))
    assert guide[0] > guide[1] + 15
    assert out.images[0][0].startswith(b"\x89PNG")
    content = _convert_to_content(out.as_tool_result())
    assert content[0].type == "text"
    assert content[1].type == "image"
    assert content[1].mimeType == "image/png"


def test_full_bleed_image_is_flagged(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    dpi = 96
    width, height = resolve_media("A4").pixel_size(dpi)
    src = tmp_path / "bleed.png"
    Image.new("RGB", (width, height), (0, 0, 0)).save(src)
    out = preview_print(settings, file_path=str(src))
    data = out.payload["data"]
    assert data["content_in_unprintable_margin"] is True
    assert any("不可印边" in warning for warning in data["warnings"])
    assert data["pages"][0]["content_in_unprintable_margin"] is True


def test_borderless_hides_margin_guide(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "note.txt"
    src.write_text("无边距", encoding="utf-8")
    out = preview_print(settings, file_path=str(src), borderless=True)
    data = out.payload["data"]
    assert data["margins_hundredths_mm"] == {
        "top": 0,
        "bottom": 0,
        "left": 0,
        "right": 0,
    }
    assert data["content_in_unprintable_margin"] is False
    view = Image.open(data["pages"][0]["view_image_path"])
    assert view.getpixel((VIEW_PAD + 1, VIEW_PAD + 1)) == (255, 255, 255)


def test_landscape_preview_is_wider_than_tall(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "wide.txt"
    src.write_text("横向排版", encoding="utf-8")
    out = preview_print(settings, file_path=str(src), orientation="landscape")
    page = out.payload["data"]["pages"][0]
    assert page["width_px"] > page["height_px"]
    assert any("横版" in note for note in out.payload["data"]["notes"])


def test_long_text_is_truncated(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "long.txt"
    src.write_text("\n".join(f"第{i}行 layout" for i in range(80)), encoding="utf-8")
    out = preview_print(settings, file_path=str(src), max_pages=1)
    data = out.payload["data"]
    assert data["preview_page_count"] == 1
    assert data["page_count"] >= 2
    assert data["truncated"] is True
    assert len(out.images) == 1
    assert any("只生成前 1 页" in warning for warning in data["warnings"])


def test_pdf_page_range(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    import fitz

    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "pages.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"P{index + 1}")
    doc.save(src)
    doc.close()
    out = preview_print(settings, file_path=str(src), page_range="2-3")
    data = out.payload["data"]
    assert data["page_count"] == 2
    assert data["preview_page_count"] == 2
    assert data["combined_view_path"]
    assert Path(data["combined_view_path"]).is_file()


def test_monochrome_ink_is_gray(tmp_path: Path, monkeypatch, fast_dpi):
    del fast_dpi
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "gray.txt"
    src.write_text("黑白", encoding="utf-8")
    out = preview_print(settings, file_path=str(src), color="monochrome", show_margins=False)
    clean = Image.open(out.payload["data"]["pages"][0]["image_path"])
    found = False
    for y in range(0, clean.height, 3):
        for x in range(0, clean.width, 3):
            pixel = clean.getpixel((x, y))
            if pixel != (255, 255, 255):
                assert pixel[0] == pixel[1] == pixel[2]
                found = True
                break
        if found:
            break
    assert found


def test_missing_source_and_unknown_paper(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    missing = preview_print(settings)
    assert missing.payload["success"] is False
    assert missing.images == []
    assert missing.as_tool_result() == missing.payload

    src = tmp_path / "note.txt"
    src.write_text("x", encoding="utf-8")
    rejected = preview_print(settings, file_path=str(src), paper="A3")
    assert rejected.payload["success"] is False
    assert "A3" in rejected.payload["error"] or "Unknown" in rejected.payload["error"]


def test_office_file_is_rejected(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    src = tmp_path / "sheet.docx"
    src.write_bytes(b"not a docx")
    out = preview_print(settings, file_path=str(src))
    assert out.payload["success"] is False
    assert "Unsupported" in out.payload["error"]


def test_content_check_ignores_white_margin():
    image = Image.new("RGB", (40, 40), "white")
    assert content_in_unprintable_margin(image, (4, 4, 4, 4)) is False
    draw = ImageDraw.Draw(image)
    draw.point((1, 1), fill=(0, 0, 0))
    assert content_in_unprintable_margin(image, (4, 4, 4, 4)) is True
    assert content_in_unprintable_margin(image, (0, 0, 0, 0)) is False
