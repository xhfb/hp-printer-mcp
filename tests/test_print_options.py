from __future__ import annotations

import pytest

from hp_printer_mcp.print_options import (
    normalize_print_settings,
    parse_page_range,
)


def test_normalize_defaults():
    settings = normalize_print_settings()
    assert settings.paper == "A4"
    assert settings.orientation == "portrait"
    assert settings.duplex == "none"
    assert settings.color == "color"
    assert settings.paper_type == "plain"
    assert settings.quality == "normal"


def test_duplex_aliases():
    settings = normalize_print_settings(duplex="long-edge")
    assert settings.duplex == "long_edge"
    settings = normalize_print_settings(duplex="short")
    assert settings.duplex == "short_edge"


def test_color_aliases():
    settings = normalize_print_settings(color="grayscale")
    assert settings.color == "monochrome"


def test_parse_page_range_all():
    assert parse_page_range("all", total_pages=5) == [0, 1, 2, 3, 4]


def test_parse_page_range_segments():
    assert parse_page_range("1-2,4", total_pages=5) == [0, 1, 3]


def test_parse_page_range_out_of_bounds():
    with pytest.raises(ValueError):
        parse_page_range("1-10", total_pages=3)


def test_invalid_paper():
    with pytest.raises(ValueError):
        normalize_print_settings(paper="INVALID")
