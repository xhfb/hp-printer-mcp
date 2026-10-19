"""PWG Raster matches libcups WRITE_PWG, including the 8x8 sRGB sample."""

from __future__ import annotations

import os
import struct

from PIL import Image

from hp_printer_mcp.pwg_raster import (
    HEADER_BYTES,
    NEG,
    OFF_NUM_COPIES,
    SYNC,
    compress_rows,
    decode_pwg,
    encode_pwg_raster,
)

W = (255, 255, 255)
Y = (255, 255, 0)
B = (0, 0, 255)
G = (0, 255, 0)
R = (255, 0, 0)

# PWG 5102.4 / current libcups. The CUPS HTML spec still shows 89 octets
# because it keeps the last two pixels as separate runs; libcups folds them.
SAMPLE_ROWS = [
    [W, Y, Y, Y, W, W, W, W],
    [Y, B, Y, W, W, W, G, W],
    [Y, Y, W, W, W, G, G, G],
    [Y, Y, Y, W, W, W, G, W],
    [W, Y, Y, Y, W, W, W, W],
    [W, W, W, W, W, W, W, W],
    [R, R, R, R, R, R, R, R],
    [R, R, R, R, R, R, R, R],
]


def _rows_bytes(pixels: list[list[tuple[int, int, int]]]) -> list[bytes]:
    return [b"".join(bytes(pixel) for pixel in row) for row in pixels]


def test_cups_8x8_srgb_packbits_is_87_bytes():
    compressed = compress_rows(_rows_bytes(SAMPLE_ROWS), 3)
    assert len(compressed) == 87
    assert compressed[:13] == bytes.fromhex("0000ffffff02ffff0003ffffff")
    assert compressed[13:35] == bytes.fromhex(
        "00feffff000000ffffff0002ffffff" "ff00ff00ffffff"
    )
    assert compressed[35:48] == bytes.fromhex("0001ffff0002ffffff0200ff00")
    assert compressed[48:64] == bytes.fromhex("0002ffff0002ffffff" "ff00ff00ffffff")
    assert compressed[64:77] == compressed[:13]
    assert compressed[77:82] == bytes.fromhex("0007ffffff")
    assert compressed[82:] == bytes.fromhex("0107ff0000")


def test_packbits_roundtrip_random_row():
    raw_rows = [os.urandom(32 * 3) for _ in range(5)]
    image = Image.frombytes("RGB", (32, 5), b"".join(raw_rows))
    # 32 px at 254 dpi needs hundredths such that n * 254 // 2540 == 32.
    encoded = encode_pwg_raster(
        [image],
        dpi=254,
        media_keyword="test",
        media_type="stationery",
        width_hundredths=320,
        height_hundredths=50,
        margins=(0, 0, 0, 0),
        duplex=False,
        tumble=False,
        sheet_back=None,
        pwg_type="srgb_8",
        print_quality=4,
    )
    decoded = decode_pwg(encoded)
    assert len(decoded) == 1
    assert decoded[0].rows == tuple(raw_rows)


def test_two_pages_one_stream_and_rotated_back_side():
    page = Image.new("RGB", (1, 1), "white")
    encoded = encode_pwg_raster(
        [page, page.copy()],
        dpi=2540,
        media_keyword="iso_a4_210x297mm",
        media_type="stationery",
        width_hundredths=1,
        height_hundredths=1,
        margins=(0, 0, 0, 0),
        duplex=True,
        tumble=False,
        sheet_back="rotated",
        pwg_type="srgb_8",
        print_quality=4,
    )
    assert encoded.startswith(SYNC)
    assert encoded.count(SYNC) == 1
    assert encoded.count(b"PwgRaster") == 2
    pages = decode_pwg(encoded)
    assert len(pages) == 2
    assert pages[0].duplex == 1 and pages[1].duplex == 1
    assert pages[0].tumble == 0
    assert pages[0].cross_feed_transform == 1
    assert pages[0].feed_transform == 1
    assert pages[1].cross_feed_transform == NEG
    assert pages[1].feed_transform == NEG
    assert pages[0].total_pages == 2
    header = encoded[4 : 4 + HEADER_BYTES]
    assert struct.unpack_from(">I", header, OFF_NUM_COPIES)[0] == 1


def test_rotated_long_edge_back_pixels_turn_180_and_copies_are_in_the_header():
    front = Image.new("RGB", (2, 2), "white")
    front.putpixel((0, 0), (255, 0, 0))
    back = front.copy()
    encoded = encode_pwg_raster(
        [front, back],
        dpi=2540,
        media_keyword="iso_a4_210x297mm",
        media_type="stationery",
        width_hundredths=2,
        height_hundredths=2,
        margins=(0, 0, 0, 0),
        duplex=True,
        tumble=False,
        sheet_back="rotated",
        pwg_type="srgb_8",
        print_quality=4,
        copies=2,
    )
    pages = decode_pwg(encoded)
    assert pages[0].rows[0][:3] == b"\xff\x00\x00"
    assert pages[1].rows[1][3:] == b"\xff\x00\x00"
    assert (pages[1].cross_feed_transform, pages[1].feed_transform) == (NEG, NEG)
    first = encoded.index(b"PwgRaster")
    second = encoded.index(b"PwgRaster", first + 1)
    assert struct.unpack_from(">I", encoded, first + OFF_NUM_COPIES)[0] == 2
    assert struct.unpack_from(">I", encoded, second + OFF_NUM_COPIES)[0] == 2


def test_rotated_short_edge_back_stays_upright():
    front = Image.new("RGB", (2, 2), "white")
    front.putpixel((0, 0), (255, 0, 0))
    encoded = encode_pwg_raster(
        [front, front.copy()],
        dpi=2540,
        media_keyword="iso_a4_210x297mm",
        media_type="stationery",
        width_hundredths=2,
        height_hundredths=2,
        margins=(0, 0, 0, 0),
        duplex=True,
        tumble=True,
        sheet_back="rotated",
        pwg_type="srgb_8",
        print_quality=4,
    )
    pages = decode_pwg(encoded)
    assert pages[0].tumble == 1 and pages[1].tumble == 1
    assert (pages[1].cross_feed_transform, pages[1].feed_transform) == (1, 1)
    assert pages[1].rows[0][:3] == b"\xff\x00\x00"


def test_normal_long_edge_back_is_not_rotated():
    page = Image.new("L", (1, 1), 0)
    encoded = encode_pwg_raster(
        [page, page.copy()],
        dpi=2540,
        media_keyword="iso_a4_210x297mm",
        media_type="stationery",
        width_hundredths=1,
        height_hundredths=1,
        margins=(0, 0, 0, 0),
        duplex=True,
        tumble=False,
        sheet_back="normal",
        pwg_type="sgray_8",
        print_quality=4,
    )
    pages = decode_pwg(encoded)
    assert pages[1].bits_per_pixel == 8
    assert (pages[1].cross_feed_transform, pages[1].feed_transform) == (1, 1)
