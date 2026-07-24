from __future__ import annotations

from pathlib import Path

from hp_printer_mcp.rasterize import rasterize_to_jpegs


def test_rasterize_txt(tmp_path: Path):
    src = tmp_path / "note.txt"
    src.write_text("MCP IPP print test\n第二行", encoding="utf-8")
    pages = rasterize_to_jpegs(src, paper="A4", color="monochrome")
    assert len(pages) >= 1
    assert pages[0][:2] == b"\xff\xd8"  # JPEG SOI
