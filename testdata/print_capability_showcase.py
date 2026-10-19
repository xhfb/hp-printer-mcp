# -*- coding: utf-8 -*-
"""Print one A4 showcase of the current driver. 10 faces, 8 sheets."""
from __future__ import annotations

import time
from pathlib import Path

import fitz

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.http_util import make_client
from hp_printer_mcp.ipp_client import (
    IppClient,
    TAG_CHARSET,
    TAG_INTEGER,
    TAG_KEYWORD,
    TAG_NATURAL_LANGUAGE,
    TAG_URI,
)
from hp_printer_mcp.print_ipp import print_file

OUT_DIR = Path(__file__).resolve().parent / "showcase"
CJK = r"C:\Windows\Fonts\msyh.ttc"
LATIN = r"C:\Windows\Fonts\arial.ttf"
MM = 72 / 25.4
PORTRAIT = fitz.Rect(0, 0, 2480 * 72 / 300, 3507 * 72 / 300)
LANDSCAPE = fitz.Rect(0, 0, 3507 * 72 / 300, 2480 * 72 / 300)


def _font(page: fitz.Page) -> None:
    page.insert_font(fontname="CJK", fontfile=CJK)
    page.insert_font(fontname="LATIN", fontfile=LATIN)


def _paragraph(page: fitz.Page, lines: list[str], y: float, size: float = 12) -> float:
    for line in lines:
        page.insert_text((18 * MM, y), line, fontname="CJK", fontsize=size, color=(0.05, 0.05, 0.05))
        y += size * 1.65
    return y


def _banner(page: fitz.Page, test_no: str, title: str) -> float:
    _font(page)
    page.insert_text((16 * MM, 16 * MM), test_no, fontname="CJK", fontsize=22, color=(0.1, 0.25, 0.55))
    page.insert_text((16 * MM, 26 * MM), title, fontname="CJK", fontsize=20, color=(0, 0, 0))
    page.draw_line(
        fitz.Point(16 * MM, 29 * MM),
        fitz.Point(page.rect.width - 16 * MM, 29 * MM),
        color=(0.1, 0.25, 0.55),
        width=1.2,
    )
    return 38 * MM


def _top_mark(page: fitz.Page) -> None:
    _font(page)
    r = page.rect
    page.insert_text((r.width / 2 - 10 * MM, 12 * MM), "▲ 上沿", fontname="CJK", fontsize=11, color=(0, 0, 0))


def _rulers(page: fitz.Page) -> None:
    _font(page)
    r = page.rect
    cx, cy = r.width / 2, r.height / 2
    for mm in range(1, 13):
        inset = mm * MM
        color = (0.05, 0.25, 0.85) if mm == 3 else (0, 0, 0)
        width = 1.4 if mm == 3 else (0.8 if mm % 5 == 0 else 0.35)
        page.draw_line(fitz.Point(cx - 70, inset), fitz.Point(cx + 28, inset), color=color, width=width)
        page.draw_line(
            fitz.Point(cx - 70, r.height - inset),
            fitz.Point(cx + 28, r.height - inset),
            color=color,
            width=width,
        )
        page.draw_line(fitz.Point(inset, cy - 55), fitz.Point(inset, cy + 24), color=color, width=width)
        page.draw_line(
            fitz.Point(r.width - inset, cy - 55),
            fitz.Point(r.width - inset, cy + 24),
            color=color,
            width=width,
        )
        page.insert_text((cx + 32, inset + 2), str(mm), fontname="LATIN", fontsize=7, color=color)
        page.insert_text((cx + 32, r.height - inset + 2), str(mm), fontname="LATIN", fontsize=7, color=color)
        page.insert_text((inset - 3, cy + 36), str(mm), fontname="LATIN", fontsize=7, color=color)
        page.insert_text((r.width - inset - 6, cy + 36), str(mm), fontname="LATIN", fontsize=7, color=color)


def _corners(page: fitz.Page) -> None:
    r = page.rect
    size = 8 * MM
    blocks = (
        (fitz.Rect(0, 0, size, size), (0.85, 0.05, 0.05)),
        (fitz.Rect(r.width - size, 0, r.width, size), (0.05, 0.55, 0.1)),
        (fitz.Rect(0, r.height - size, size, r.height), (0.1, 0.2, 0.85)),
        (fitz.Rect(r.width - size, r.height - size, r.width, r.height), (0.95, 0.45, 0.05)),
    )
    for rect, color in blocks:
        page.draw_rect(rect, color=color, fill=color, width=0)


def _swatches(page: fitz.Page, y: float) -> float:
    colors = (
        ((0.85, 0.05, 0.05), "红"),
        ((0.05, 0.55, 0.1), "绿"),
        ((0.1, 0.25, 0.85), "蓝"),
        ((0, 0, 0), "黑"),
        ((0, 0.7, 0.75), "青"),
        ((0.85, 0.1, 0.55), "品红"),
        ((0.95, 0.75, 0.05), "黄"),
    )
    x = 18 * MM
    for color, label in colors:
        rect = fitz.Rect(x, y, x + 16 * MM, y + 16 * MM)
        page.draw_rect(rect, color=color, fill=color, width=0)
        page.insert_text((x, y + 21 * MM), label, fontname="CJK", fontsize=10, color=(0, 0, 0))
        x += 22 * MM
    return y + 28 * MM


def _long_edge(path: Path) -> None:
    doc = fitz.open()
    front = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    _font(front)
    _corners(front)
    _rulers(front)
    _top_mark(front)
    y = _banner(front, "测试 1 · 正面", "彩色、中文、边距、长边双面")
    y = _paragraph(
        front,
        [
            "整套共 8 张纸、10 个页面。请按测试编号看，不要按出纸先后。",
            "本页检测：七个色块是否有颜色，中文是否成方块。",
            "四角色块贴着纸边：左上红、右上绿、左下蓝、右下橙。",
            "蓝线是 3 毫米。请记下四边第一个还能看见的数字。",
            "背面是测试 1 反面。沿左边长边翻开。",
            "翻开后，反面的「▲ 上沿」应和本页上沿是纸的同一头。",
        ],
        y,
    )
    _paragraph(front, ["中文打印测试  HP Smart Tank 750  ABC 0123456789"], y + 4 * MM, size=14)
    _swatches(front, 175 * MM)
    front.insert_text(
        (18 * MM, PORTRAIT.height - 18 * MM),
        "普通质量 · 有边距 · 单份 · 左 = 长边装订边",
        fontname="CJK",
        fontsize=11,
        color=(0, 0, 0),
    )

    back = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    _top_mark(back)
    y = _banner(back, "测试 1 · 反面", "长边翻转是否正确")
    _paragraph(
        back,
        [
            "检测方法：沿左边（长边）把纸翻开。",
            "正确：这段文字正向，上沿与正面上沿是同一头。",
            "失败：文字头朝下，或左右镜像。",
            "失败：这一面跑到了另一张纸上，说明没有双面。",
            "这一面不测边距，请以正面的毫米刻度为准。",
        ],
        y,
        size=14,
    )
    back.insert_text((40 * MM, 150 * MM), "长边反面", fontname="CJK", fontsize=48, color=(0.1, 0.25, 0.55))
    doc.save(path)
    doc.close()


def _short_edge(path: Path) -> None:
    doc = fitz.open()
    front = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    _top_mark(front)
    y = _banner(front, "测试 2 · 正面", "短边双面")
    _paragraph(
        front,
        [
            "本页只检测翻转方向，不测边距和颜色。",
            "请沿上边（短边）把纸翻开，不要沿左边翻。",
            "正确：反面文字正向，反面的上沿仍是这一头。",
            "失败：必须改成沿左边翻，文字才正向。",
            "那说明短边没有生效，实际仍按长边在翻。",
        ],
        y,
        size=14,
    )
    front.draw_line(fitz.Point(40 * MM, 20 * MM), fitz.Point(PORTRAIT.width - 40 * MM, 20 * MM), color=(0.85, 0.1, 0.1), width=3)
    front.insert_text((18 * MM, PORTRAIT.height - 18 * MM), "红线在短边一侧，翻纸时以这一头为轴", fontname="CJK", fontsize=11)

    back = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    _top_mark(back)
    y = _banner(back, "测试 2 · 反面", "短边翻转结果")
    _paragraph(
        back,
        [
            "若你是沿上边翻过来的，本段应正向可读。",
            "上沿的红线应仍在纸的这一头。",
            "若文字倒了，请说明你是沿哪一条边翻开的。",
        ],
        y,
        size=14,
    )
    back.draw_line(fitz.Point(40 * MM, 20 * MM), fitz.Point(PORTRAIT.width - 40 * MM, 20 * MM), color=(0.85, 0.1, 0.1), width=3)
    back.insert_text((40 * MM, 150 * MM), "短边反面", fontname="CJK", fontsize=48, color=(0.7, 0.1, 0.1))
    doc.save(path)
    doc.close()


def _copies(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    y = _banner(page, "测试 3", "份数：应出两张相同的单面")
    _paragraph(
        page,
        [
            "这个作业请求 2 份。两张纸的内容应当完全一样。",
            "请数纸：正确是 2 张，失败是只有 1 张。",
            "两张内容相同是对的，不是印重了。",
            "面板上的份数可能显示 1。请以纸张数量为准。",
            "本次是单面。双面逐份用的是同一套重复规则。",
        ],
        y,
        size=14,
    )
    page.insert_text((36 * MM, 160 * MM), "两张", fontname="CJK", fontsize=60, color=(0.1, 0.25, 0.55))
    doc.save(path)
    doc.close()


def _landscape(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=LANDSCAPE.width, height=LANDSCAPE.height)
    _font(page)
    # Arrow toward the top edge of the landscape composition.
    cx = LANDSCAPE.width / 2
    page.draw_line(fitz.Point(cx, 28 * MM), fitz.Point(cx, 12 * MM), color=(0, 0, 0), width=2)
    page.draw_line(fitz.Point(cx - 4 * MM, 16 * MM), fitz.Point(cx, 10 * MM), color=(0, 0, 0), width=2)
    page.draw_line(fitz.Point(cx + 4 * MM, 16 * MM), fitz.Point(cx, 10 * MM), color=(0, 0, 0), width=2)
    page.insert_text((cx - 28 * MM, 36 * MM), "阅读时此边朝上", fontname="CJK", fontsize=16, color=(0, 0, 0))
    page.insert_text((22 * MM, 58 * MM), "测试 4 · 横版", fontname="CJK", fontsize=28, color=(0.1, 0.25, 0.55))
    lines = [
        "本页按横版排版，再转进竖向走纸。",
        "出纸后把纸顺时针转 90 度。",
        "正确：箭头朝上，这段文字正向。",
        "失败：箭头朝下，或文字镜像。",
        "不需要再沿长边或短边去翻，这是单面。",
    ]
    y = 78 * MM
    for line in lines:
        page.insert_text((22 * MM, y), line, fontname="CJK", fontsize=16, color=(0.05, 0.05, 0.05))
        y += 12 * MM
    doc.save(path)
    doc.close()


def _mono(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    y = _banner(page, "测试 5", "黑白")
    y = _paragraph(
        page,
        [
            "本页应完全没有彩色，色块都变成灰色或黑色。",
            "正确：红、绿、蓝三块只是深浅不同的灰。",
            "失败：还能看出红、绿或蓝。",
            "这是单面，不测翻转。",
        ],
        y,
        size=14,
    )
    _swatches(page, y + 8 * MM)
    doc.save(path)
    doc.close()


def _borderless(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    _font(page)
    _corners(page)
    _rulers(page)
    y = _banner(page, "测试 6", "无边距")
    _paragraph(
        page,
        [
            "四边距设为 0。请与测试 1 的正面比较。",
            "正确：色块和毫米线比测试 1 更靠近纸边。",
            "请记下四边第一个还能看见的数字。",
            "失败：和测试 1 的留白差不多，说明无边距没生效。",
            "这是单面。蓝线仍然表示 3 毫米的位置。",
        ],
        y,
        size=13,
    )
    doc.save(path)
    doc.close()


def _quality(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PORTRAIT.width, height=PORTRAIT.height)
    y = _banner(page, "测试 7", "高质量细线")
    y = _paragraph(
        page,
        [
            "本页使用最高打印质量，光栅仍是 300 dpi。",
            "请和测试 1 的文字比一比细线是否更清楚。",
            "看不出差别也告诉我。这是单面。",
        ],
        y,
        size=14,
    )
    x0, x1 = 20 * MM, PORTRAIT.width - 20 * MM
    y_line = y + 8 * MM
    for index, width in enumerate((0.2, 0.4, 0.8, 1.5, 3)):
        page.draw_line(fitz.Point(x0, y_line), fitz.Point(x1, y_line), color=(0, 0, 0), width=width)
        page.insert_text((x0, y_line - 3 * MM), f"{width} pt", fontname="LATIN", fontsize=8)
        y_line += 16 * MM
    page.insert_text((20 * MM, y_line + 6 * MM), "细线样品  Il1  0O  中文细字", fontname="CJK", fontsize=9)
    doc.save(path)
    doc.close()


def build_all() -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    specs = [
        ("01_long_edge.pdf", _long_edge, {"duplex": "long_edge", "copies": 1, "orientation": "portrait", "color": "color", "borderless": False, "quality": "normal"}),
        ("02_short_edge.pdf", _short_edge, {"duplex": "short_edge", "copies": 1, "orientation": "portrait", "color": "color", "borderless": False, "quality": "normal"}),
        ("03_copies.pdf", _copies, {"duplex": "none", "copies": 2, "orientation": "portrait", "color": "color", "borderless": False, "quality": "normal"}),
        ("04_landscape.pdf", _landscape, {"duplex": "none", "copies": 1, "orientation": "landscape", "color": "color", "borderless": False, "quality": "normal"}),
        ("05_mono.pdf", _mono, {"duplex": "none", "copies": 1, "orientation": "portrait", "color": "monochrome", "borderless": False, "quality": "normal"}),
        ("06_borderless.pdf", _borderless, {"duplex": "none", "copies": 1, "orientation": "portrait", "color": "color", "borderless": True, "quality": "normal"}),
        ("07_quality.pdf", _quality, {"duplex": "none", "copies": 1, "orientation": "portrait", "color": "color", "borderless": False, "quality": "best"}),
    ]
    jobs = []
    for name, builder, options in specs:
        path = OUT_DIR / name
        builder(path)
        jobs.append({"path": path, **options})
    return jobs


def _check_pixmap(path: Path, orientation: str) -> None:
    doc = fitz.open(path)
    try:
        for index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), alpha=False)
            if orientation == "landscape":
                expect = (3507, 2480)
            else:
                expect = (2480, 3507)
            if (pix.width, pix.height) != expect:
                raise SystemExit(f"{path.name} page {index + 1} is {pix.width}x{pix.height}, expected {expect}")
    finally:
        doc.close()


def _printer_ready() -> None:
    settings = load_settings()
    with make_client(settings, timeout=15) as client:
        ipp = IppClient(
            ipp_uri=settings.ipp_uri,
            client=client,
            username=settings.ipp_username,
            password=settings.ipp_password,
        )
        resp = ipp.get_printer_attributes(["printer-state", "printer-state-reasons", "media-ready"])
    state = resp.first("printer-state")
    ready = resp.attributes.get("media-ready")
    reasons = resp.attributes.get("printer-state-reasons")
    print("printer", state, reasons, ready)
    if state != 3:
        raise SystemExit(f"printer is not idle: {state} {reasons}")
    if ready != ["iso_a4_210x297mm"]:
        raise SystemExit(f"tray is not A4: {ready}")


def _wait_job(settings, job_id: int) -> None:
    names = {3: "pending", 4: "pending-held", 5: "processing", 6: "processing-stopped", 7: "canceled", 8: "aborted", 9: "completed"}
    want = ["job-state", "job-state-reasons", "job-impressions-completed", "job-media-sheets-completed"]
    with make_client(settings, timeout=15) as client:
        ipp = IppClient(
            ipp_uri=settings.ipp_uri,
            client=client,
            username=settings.ipp_username,
            password=settings.ipp_password,
        )
        for i in range(36):
            attrs = [
                (TAG_CHARSET, "attributes-charset", "utf-8"),
                (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
                (TAG_URI, "printer-uri", settings.ipp_uri),
                (TAG_INTEGER, "job-id", job_id),
                (TAG_KEYWORD, "requested-attributes", want[0]),
            ]
            for name in want[1:]:
                attrs.append((TAG_KEYWORD, "", name))
            resp = ipp.request(0x0009, operation_attributes=attrs)
            state = resp.first("job-state")
            print(
                " poll",
                i,
                names.get(state, state),
                "sheets",
                resp.first("job-media-sheets-completed"),
                "faces",
                resp.first("job-impressions-completed"),
                resp.attributes.get("job-state-reasons"),
            )
            if state in (7, 8, 9):
                if state != 9:
                    raise SystemExit(f"job {job_id} ended as {names.get(state)}")
                return
            time.sleep(5)
    raise SystemExit(f"job {job_id} still running")


def main() -> None:
    jobs = build_all()
    for job in jobs:
        _check_pixmap(job["path"], job["orientation"])
    _printer_ready()
    settings = load_settings()
    for job in jobs:
        print("PRINT", job["path"].name, {k: v for k, v in job.items() if k != "path"})
        result = print_file(
            settings,
            file_path=str(job["path"]),
            copies=job["copies"],
            duplex=job["duplex"],
            orientation=job["orientation"],
            paper="A4",
            paper_type="plain",
            color=job["color"],
            quality=job["quality"],
            borderless=job["borderless"],
        )
        print(" result", result.get("success"), result.get("error"), (result.get("data") or {}).get("job_id"), (result.get("data") or {}).get("page_count"))
        if not result.get("success"):
            raise SystemExit(f"print failed: {result.get('error')}")
        _wait_job(settings, int(result["data"]["job_id"]))


if __name__ == "__main__":
    main()
