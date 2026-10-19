"""Capability checks and a single multi-page PWG job. No printer I/O."""

from __future__ import annotations

from unittest.mock import patch

from PIL import Image

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.ipp_client import IppResponse
from hp_printer_mcp.media import resolve_media
from hp_printer_mcp.print_ipp import collated_raster_pages, print_file
from hp_printer_mcp.print_options import normalize_print_settings
from hp_printer_mcp.printer_caps import PrinterCaps, resolve_print_ticket


def _caps(**overrides) -> PrinterCaps:
    caps = PrinterCaps(
        document_formats=["image/pwg-raster", "image/jpeg"],
        media_supported=[
            "iso_a4_210x297mm",
            "iso_a6_105x148mm",
            "na_index-4x6_4x6in",
            "na_number-10_4.125x9.5in",
        ],
        media_types=["stationery", "photographic-glossy", "com.hp-matte-presentation"],
        media_sources=["main", "photo"],
        media_ready=["iso_a4_210x297mm"],
        margin_top=[296, 0],
        margin_bottom=[296, 0],
        margin_left=[296, 0],
        margin_right=[296, 0],
        default_margins=(296, 296, 296, 296),
        sides=["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
        color_modes=["auto", "auto-monochrome", "color", "monochrome"],
        qualities=[3, 4, 5],
        pwg_resolutions=[(72, 72, 3), (300, 300, 3)],
        pwg_types=["srgb_8", "sgray_8"],
        sheet_back="rotated",
        print_scaling=["auto", "none"],
        copies_supported=[(1, 99)],
        media_col_database=[
            {
                "media-size": {"x-dimension": 21000, "y-dimension": 29700},
                "media-type": "stationery",
                "media-top-margin": 296,
                "media-bottom-margin": 296,
                "media-left-margin": 296,
                "media-right-margin": 296,
            },
            {
                "media-size": {"x-dimension": 21000, "y-dimension": 29700},
                "media-type": "photographic-glossy",
                "media-top-margin": 0,
                "media-bottom-margin": 0,
                "media-left-margin": 0,
                "media-right-margin": 0,
            },
        ],
    )
    for key, value in overrides.items():
        setattr(caps, key, value)
    return caps


def test_duplex_copies_are_repeated_and_padded_to_full_sheets():
    front = Image.new("RGB", (2, 2), "white")
    back = Image.new("RGB", (2, 2), "black")
    odd = Image.new("RGB", (2, 2), "red")
    repeated, extras = collated_raster_pages([front, back], 2, duplex=True)
    assert repeated == [front, back, front, back]
    assert extras == []
    padded, blanks = collated_raster_pages([odd], 2, duplex=True)
    assert len(blanks) == 1
    assert len(padded) == 4
    assert padded[0] is odd and padded[2] is odd
    assert padded[1] is blanks[0] and padded[3] is blanks[0]
    for image in blanks:
        image.close()


def test_a4_pixels_at_300_dpi():
    assert resolve_media("A4").pixel_size(300) == (2480, 3507)


def test_number10_hundredths_follow_the_keyword():
    media = resolve_media("#10")
    assert media.keyword == "na_number-10_4.125x9.5in"
    assert media.x == 10477
    assert media.y == 24130


def test_ticket_media_col_margins_and_rejections():
    plain = resolve_print_ticket(
        normalize_print_settings(paper="A4", paper_type="plain", copies=2),
        _caps(),
        source_suffix=".txt",
    )
    assert plain.margins == (296, 296, 296, 296)
    assert plain.media_type == "stationery"
    assert plain.dpi == 300
    assert plain.document_format == "image/pwg-raster"
    assert plain.print_scaling == "none"
    names = [member[1] for member in plain.media_col.members]
    assert "media-source" in names
    assert "media-type" in names

    photo = resolve_print_ticket(
        normalize_print_settings(paper="A4", paper_type="photo", borderless=True),
        _caps(),
        source_suffix=".jpg",
    )
    assert photo.margins == (0, 0, 0, 0)
    assert photo.media_type == "photographic-glossy"

    try:
        resolve_print_ticket(
            normalize_print_settings(paper="A4", paper_type="plain", borderless=True),
            _caps(),
            source_suffix=".txt",
        )
    except ValueError as exc:
        assert "photographic-glossy" in str(exc)
    else:
        raise AssertionError("borderless plain should be rejected")

    try:
        resolve_print_ticket(
            normalize_print_settings(copies=100),
            _caps(),
            source_suffix=".txt",
        )
    except ValueError as exc:
        assert "99" in str(exc)
    else:
        raise AssertionError("copies 100 should be rejected")

    try:
        resolve_print_ticket(
            normalize_print_settings(paper="Legal"),
            _caps(),
            source_suffix=".txt",
        )
    except ValueError as exc:
        assert "na_legal_8.5x14in" in str(exc)
    else:
        raise AssertionError("unsupported media should be rejected")


def _fake_response(job_id: int) -> IppResponse:
    return IppResponse(status_code=0, request_id=1, attributes={"job-id": [job_id]})


def test_print_file_sends_one_pwg_job(tmp_path, monkeypatch):
    monkeypatch.setenv("HP_PRINTER_HOST", "192.0.2.10")
    monkeypatch.setenv("HP_JOB_TMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("HP_PRINTER_ENV_FILE", str(tmp_path / "missing.env"))
    settings = load_settings()
    src = tmp_path / "note.txt"
    src.write_text("page", encoding="utf-8")

    calls: list[dict] = []

    def fake_print(self, document, **kwargs):
        calls.append({"document": document, **kwargs})
        return _fake_response(17)

    def fake_pages(path, **kwargs):
        width, height = resolve_media("A4").pixel_size(kwargs["dpi"])
        if kwargs["orientation"] == "landscape":
            width, height = height, width
        return [
            Image.new("RGB", (width, height), "white"),
            Image.new("RGB", (width, height), "white"),
        ]

    with (
        patch("hp_printer_mcp.print_ipp.fetch_printer_caps", return_value=_caps()),
        patch("hp_printer_mcp.print_ipp.IppClient.print_job", fake_print),
        patch("hp_printer_mcp.print_ipp.IppClient.get_printer_attributes", side_effect=AssertionError("network")),
        patch("hp_printer_mcp.print_ipp.rasterize_to_images", fake_pages),
    ):
        result = print_file(
            settings,
            file_path=str(src),
            copies=3,
            duplex="long_edge",
            paper="A4",
        )

    assert result["success"] is True, result
    assert len(calls) == 1
    assert calls[0]["copies"] == 1
    assert calls[0]["sides"] == "two-sided-long-edge"
    assert calls[0]["document_format"] == "image/pwg-raster"
    assert calls[0]["document"].count(b"RaS2") == 1
    assert calls[0]["document"].count(b"PwgRaster") == 6
    assert result["data"]["copies"] == 3
    assert result["data"]["job_id"] == 17
    assert result["data"]["job_ids"] == [17]
    assert result["data"]["page_count"] == 2
    assert result["data"]["media_type"] == "stationery"


def test_jpeg_fallback_is_one_job_per_page(tmp_path, monkeypatch):
    monkeypatch.setenv("HP_PRINTER_HOST", "192.0.2.10")
    monkeypatch.setenv("HP_JOB_TMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("HP_PRINTER_ENV_FILE", str(tmp_path / "missing.env"))
    settings = load_settings()
    src = tmp_path / "note.txt"
    src.write_text("page", encoding="utf-8")
    calls: list[str] = []

    def fake_print(self, document, **kwargs):
        calls.append(kwargs["document_format"])
        return _fake_response(len(calls))

    def fake_pages(path, **kwargs):
        width, height = resolve_media("A4").pixel_size(kwargs["dpi"])
        return [Image.new("RGB", (width, height), "white") for _ in range(2)]

    caps = _caps(document_formats=["image/jpeg"])
    with (
        patch("hp_printer_mcp.print_ipp.fetch_printer_caps", return_value=caps),
        patch("hp_printer_mcp.print_ipp.IppClient.print_job", fake_print),
        patch("hp_printer_mcp.print_ipp.rasterize_to_images", fake_pages),
    ):
        result = print_file(
            settings,
            file_path=str(src),
            copies=2,
            duplex="short_edge",
        )

    assert result["success"] is True, result
    assert calls == ["image/jpeg", "image/jpeg"]
    assert result["data"]["job_id"] is None
    assert result["data"]["job_ids"] == [1, 2]
    warning_text = " ".join(result["data"]["warnings"])
    assert "duplex" in warning_text
    assert "collate" in warning_text
