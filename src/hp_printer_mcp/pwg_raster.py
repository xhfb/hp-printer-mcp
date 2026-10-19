"""PWG Raster encoder (image/pwg-raster) matching CUPS WRITE_PWG.

The stream is one big-endian ``RaS2`` sync word, then one 1796-byte page
header per page, then CUPS PackBits rows. Page headers are big-endian and
mostly zero, with ``MediaClass`` set to ``PwgRaster``. Compression is implied;
``cupsCompression`` stays 0.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image

HEADER_BYTES = 1796
SYNC = b"RaS2"
NEG = 0xFFFFFFFF

OFF_MEDIA_CLASS = 0
OFF_MEDIA_TYPE = 128
OFF_DUPLEX = 272
OFF_HW_RES = 276
OFF_BBOX = 284
OFF_LEADING = 308
OFF_MEDIA_POSITION = 324
OFF_NUM_COPIES = 340
OFF_ORIENTATION = 344
OFF_PAGE_SIZE = 352
OFF_TUMBLE = 368
OFF_WIDTH = 372
OFF_HEIGHT = 376
OFF_BITS_COLOR = 384
OFF_BITS_PIXEL = 388
OFF_BYTES_LINE = 392
OFF_COLOR_ORDER = 396
OFF_COLOR_SPACE = 400
OFF_NUM_COLORS = 420
OFF_INTEGER = 452
OFF_PAGE_SIZE_NAME = 1732

CSPACE_SGRAY = 18
CSPACE_SRGB = 19

# cupsInteger indexes from PWG 5102.4
IDX_TOTAL_PAGES = 0
IDX_CROSS = 1
IDX_FEED = 2
IDX_BOX_LEFT = 3
IDX_BOX_TOP = 4
IDX_BOX_RIGHT = 5
IDX_BOX_BOTTOM = 6
IDX_ALTERNATE = 7
IDX_QUALITY = 8


@dataclass(frozen=True)
class DecodedPage:
    width: int
    height: int
    dpi: tuple[int, int]
    duplex: int
    tumble: int
    color_space: int
    bits_per_pixel: int
    cross_feed_transform: int
    feed_transform: int
    total_pages: int
    rows: tuple[bytes, ...]


def back_side_transforms(sheet_back: str | None, *, tumble: bool) -> tuple[int, int]:
    """Header transforms for a duplex back side. Front sides stay ``(1, 1)``.

    Values follow PWG 5102.4 Table 9. For ``rotated`` (this Smart Tank), the
    long-edge back side is a 180 degree coordinate system and the short-edge
    back side stays upright. The bitmap must actually be in that coordinate
    system; this printer does not rotate upright pixels from the flags alone.
    """
    mode = (sheet_back or "normal").strip().lower()
    if mode == "flipped":
        return (NEG, 1) if tumble else (1, NEG)
    if mode == "rotated":
        return (1, 1) if tumble else (NEG, NEG)
    if mode == "manual-tumble" and tumble:
        return (NEG, NEG)
    return (1, 1)


def orient_for_transform(image: Image.Image, cross: int, feed: int) -> Image.Image:
    """Put a page into the coordinate system declared by the transform flags."""
    if cross == NEG and feed == NEG:
        return image.transpose(Image.Transpose.ROTATE_180)
    if cross == NEG and feed == 1:
        return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if cross == 1 and feed == NEG:
        return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


def compress_row(pixels: bytes, bpp: int) -> bytes:
    """CUPS modified PackBits for one row. ``bpp`` is bytes per pixel."""
    if bpp <= 0 or len(pixels) % bpp != 0:
        raise ValueError("raster row length is not a multiple of the pixel size")
    out = bytearray()
    n = len(pixels)
    ptr = 0
    plast = n - bpp
    while ptr < n:
        start = ptr
        ptr += bpp
        if ptr >= n:
            out.append(0)
            out += pixels[start : start + bpp]
            continue
        if pixels[start : start + bpp] == pixels[ptr : ptr + bpp]:
            count = 2
            while count < 128 and ptr < plast:
                nxt = ptr + bpp
                if pixels[ptr:nxt] != pixels[nxt : nxt + bpp]:
                    break
                count += 1
                ptr += bpp
            out.append(count - 1)
            out += pixels[ptr : ptr + bpp]
            ptr += bpp
        else:
            count = 1
            while count < 128 and ptr < plast:
                nxt = ptr + bpp
                if pixels[ptr:nxt] == pixels[nxt : nxt + bpp]:
                    break
                count += 1
                ptr += bpp
            if ptr >= plast and count < 128:
                count += 1
                ptr += bpp
            out.append((257 - count) & 0xFF)
            out += pixels[start : start + count * bpp]
    return bytes(out)


def compress_rows(rows: list[bytes], bpp: int) -> bytes:
    out = bytearray()
    index = 0
    total = len(rows)
    while index < total:
        repeat = 1
        while (
            repeat < 256
            and index + repeat < total
            and rows[index + repeat] == rows[index]
        ):
            repeat += 1
        out.append(repeat - 1)
        out += compress_row(rows[index], bpp)
        index += repeat
    return bytes(out)


def _put_u32(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", buf, offset, value & 0xFFFFFFFF)


def _put_str(buf: bytearray, offset: int, text: str, length: int = 64) -> None:
    raw = text.encode("utf-8")[: length - 1]
    buf[offset : offset + len(raw)] = raw


def _image_rows(image: Image.Image, *, pwg_type: str) -> tuple[list[bytes], int, int]:
    if pwg_type == "sgray_8":
        gray = image.convert("L")
        bpp = 1
        color_space = CSPACE_SGRAY
        raw = gray.tobytes()
        width, height = gray.size
    elif pwg_type == "srgb_8":
        rgb = image.convert("RGB")
        bpp = 3
        color_space = CSPACE_SRGB
        raw = rgb.tobytes()
        width, height = rgb.size
    else:
        raise ValueError(f"Unsupported PWG raster type {pwg_type!r}")
    row_bytes = width * bpp
    rows = [raw[i : i + row_bytes] for i in range(0, len(raw), row_bytes)]
    if len(rows) != height:
        raise ValueError("image buffer does not match its height")
    return rows, bpp, color_space


def _page_header(
    *,
    width: int,
    height: int,
    dpi: int,
    page_size_points: tuple[int, int],
    media_name: str,
    media_type: str,
    duplex: bool,
    tumble: bool,
    cross_feed: int,
    feed: int,
    total_pages: int,
    num_copies: int,
    print_quality: int,
    color_space: int,
    bits_per_pixel: int,
    margins: tuple[int, int, int, int],
    size_hundredths: tuple[int, int],
) -> bytes:
    buf = bytearray(HEADER_BYTES)
    _put_str(buf, OFF_MEDIA_CLASS, "PwgRaster")
    _put_str(buf, OFF_MEDIA_TYPE, media_type)
    _put_u32(buf, OFF_DUPLEX, 1 if duplex else 0)
    _put_u32(buf, OFF_HW_RES, dpi)
    _put_u32(buf, OFF_HW_RES + 4, dpi)
    _put_u32(buf, OFF_LEADING, 0)
    _put_u32(buf, OFF_MEDIA_POSITION, 1)
    _put_u32(buf, OFF_NUM_COPIES, num_copies)
    _put_u32(buf, OFF_ORIENTATION, 0)
    _put_u32(buf, OFF_PAGE_SIZE, page_size_points[0])
    _put_u32(buf, OFF_PAGE_SIZE + 4, page_size_points[1])
    _put_u32(buf, OFF_TUMBLE, 1 if tumble else 0)
    _put_u32(buf, OFF_WIDTH, width)
    _put_u32(buf, OFF_HEIGHT, height)
    bits_per_color = 8
    _put_u32(buf, OFF_BITS_COLOR, bits_per_color)
    _put_u32(buf, OFF_BITS_PIXEL, bits_per_pixel)
    _put_u32(buf, OFF_BYTES_LINE, width * (bits_per_pixel // 8))
    _put_u32(buf, OFF_COLOR_ORDER, 0)
    _put_u32(buf, OFF_COLOR_SPACE, color_space)
    _put_u32(buf, OFF_NUM_COLORS, bits_per_pixel // bits_per_color)

    top, bottom, left, right = margins
    size_x, size_y = size_hundredths
    box_left = dpi * left // 2540
    box_top = dpi * top // 2540
    box_right = dpi * (size_x - right) // 2540
    box_bottom = dpi * (size_y - bottom) // 2540
    if box_top > 0:
        box_top -= 1
    if box_right > 0:
        box_right -= 1
    point_left = 72 * left // 2540
    point_bottom = 72 * bottom // 2540
    point_right = 72 * (size_x - right) // 2540
    point_top = 72 * (size_y - top) // 2540
    for index, value in enumerate((point_left, point_bottom, point_right, point_top)):
        _put_u32(buf, OFF_BBOX + 4 * index, value)

    integers = {
        IDX_TOTAL_PAGES: total_pages,
        IDX_CROSS: cross_feed,
        IDX_FEED: feed,
        IDX_BOX_LEFT: box_left,
        IDX_BOX_TOP: box_top,
        IDX_BOX_RIGHT: box_right,
        IDX_BOX_BOTTOM: box_bottom,
        IDX_ALTERNATE: 0xFFFFFF,
        IDX_QUALITY: print_quality,
    }
    for index, value in integers.items():
        _put_u32(buf, OFF_INTEGER + 4 * index, value)
    _put_str(buf, OFF_PAGE_SIZE_NAME, media_name)
    if len(buf) != HEADER_BYTES:
        raise RuntimeError("PWG page header is not 1796 bytes")
    return bytes(buf)


def encode_pwg_raster(
    pages: list[Image.Image],
    *,
    dpi: int,
    media_keyword: str,
    media_type: str,
    width_hundredths: int,
    height_hundredths: int,
    margins: tuple[int, int, int, int],
    duplex: bool,
    tumble: bool,
    sheet_back: str | None,
    pwg_type: str,
    print_quality: int,
    copies: int = 1,
) -> bytes:
    """Encode portrait-feed pages into one PWG Raster document."""
    if not pages:
        raise ValueError("PWG raster needs at least one page")
    if dpi < 1:
        raise ValueError("dpi must be >= 1")
    if copies < 1:
        raise ValueError("copies must be >= 1")
    expected = (width_hundredths * dpi // 2540, height_hundredths * dpi // 2540)
    page_points = (72 * width_hundredths // 2540, 72 * height_hundredths // 2540)
    back = back_side_transforms(sheet_back, tumble=tumble)
    chunks = [SYNC]
    total = len(pages)
    for index, image in enumerate(pages):
        if image.size != expected:
            raise ValueError(
                f"page {index + 1} is {image.size[0]}x{image.size[1]} px, "
                f"expected {expected[0]}x{expected[1]} px at {dpi} dpi"
            )
        cross, feed = back if duplex and index % 2 == 1 else (1, 1)
        oriented = orient_for_transform(image, cross, feed)
        try:
            rows, bpp, color_space = _image_rows(oriented, pwg_type=pwg_type)
        finally:
            if oriented is not image:
                oriented.close()
        chunks.append(
            _page_header(
                width=expected[0],
                height=expected[1],
                dpi=dpi,
                page_size_points=page_points,
                media_name=media_keyword,
                media_type=media_type,
                duplex=duplex,
                tumble=tumble,
                cross_feed=cross,
                feed=feed,
                total_pages=total,
                num_copies=copies,
                print_quality=print_quality,
                color_space=color_space,
                bits_per_pixel=bpp * 8,
                margins=margins,
                size_hundredths=(width_hundredths, height_hundredths),
            )
        )
        chunks.append(compress_rows(rows, bpp))
    return b"".join(chunks)


def _u32(header: bytes, offset: int) -> int:
    return struct.unpack_from(">I", header, offset)[0]


def _decode_row(buf: memoryview, offset: int, row_bytes: int, bpp: int) -> tuple[bytes, int]:
    row = bytearray()
    while len(row) < row_bytes:
        if offset >= len(buf):
            raise ValueError("truncated PWG raster row")
        ctrl = buf[offset]
        offset += 1
        if ctrl == 128:
            row.extend(b"\xff" * (row_bytes - len(row)))
            break
        if ctrl & 0x80:
            count = (257 - ctrl) * bpp
            row.extend(buf[offset : offset + count])
            offset += count
        else:
            pixel = bytes(buf[offset : offset + bpp])
            offset += bpp
            row.extend(pixel * (ctrl + 1))
    if len(row) != row_bytes:
        raise ValueError(f"decoded row is {len(row)} bytes, expected {row_bytes}")
    return bytes(row), offset


def decode_pwg(data: bytes) -> list[DecodedPage]:
    if not data.startswith(SYNC):
        raise ValueError("PWG raster does not start with RaS2")
    view = memoryview(data)
    offset = 4
    pages: list[DecodedPage] = []
    while offset + HEADER_BYTES <= len(data):
        header = bytes(view[offset : offset + HEADER_BYTES])
        offset += HEADER_BYTES
        if not header.startswith(b"PwgRaster"):
            raise ValueError("PWG page header is missing MediaClass PwgRaster")
        width = _u32(header, OFF_WIDTH)
        height = _u32(header, OFF_HEIGHT)
        bits = _u32(header, OFF_BITS_PIXEL)
        bpp = bits // 8
        row_bytes = _u32(header, OFF_BYTES_LINE)
        rows: list[bytes] = []
        while len(rows) < height:
            if offset >= len(view):
                raise ValueError("truncated PWG raster page")
            repeat = view[offset] + 1
            offset += 1
            row, offset = _decode_row(view, offset, row_bytes, bpp)
            for _ in range(repeat):
                rows.append(row)
                if len(rows) == height:
                    break
        pages.append(
            DecodedPage(
                width=width,
                height=height,
                dpi=(_u32(header, OFF_HW_RES), _u32(header, OFF_HW_RES + 4)),
                duplex=_u32(header, OFF_DUPLEX),
                tumble=_u32(header, OFF_TUMBLE),
                color_space=_u32(header, OFF_COLOR_SPACE),
                bits_per_pixel=bits,
                cross_feed_transform=_u32(header, OFF_INTEGER + 4 * IDX_CROSS),
                feed_transform=_u32(header, OFF_INTEGER + 4 * IDX_FEED),
                total_pages=_u32(header, OFF_INTEGER + 4 * IDX_TOTAL_PAGES),
                rows=tuple(rows),
            )
        )
    if offset != len(data):
        raise ValueError("trailing bytes after PWG raster")
    return pages
