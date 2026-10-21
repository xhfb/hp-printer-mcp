import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.copy import copy_document as run_copy_document
from hp_printer_mcp.discovery import discover_printer as run_discover_printer
from hp_printer_mcp.discovery import get_device_status as run_get_device_status
from hp_printer_mcp.print_ipp import cancel_print_job as run_cancel_print_job
from hp_printer_mcp.print_ipp import get_ipp_printer_state
from hp_printer_mcp.print_ipp import is_printer_ready
from hp_printer_mcp.print_ipp import list_print_jobs as run_list_print_jobs
from hp_printer_mcp.print_ipp import print_file as run_print_file
from hp_printer_mcp.print_ipp import print_queue_count
from hp_printer_mcp.preview import preview_print as run_preview_print
from hp_printer_mcp.scan_escl import get_scan_capabilities as run_get_scan_capabilities
from hp_printer_mcp.scan_escl import get_scanner_status as run_get_scanner_status
from hp_printer_mcp.scan_escl import scan_to_file as run_scan_to_file
from hp_printer_mcp.supplies import get_supply_levels as run_get_supply_levels

_HP_VS_DETONG = (
    "【HP Smart Tank 750】局域网 A4 办公喷墨/扫描一体机（IPP/eSCL），"
    "不是德佟热敏标签机。禁止用本工具打标签；"
    "标签请用 detong_list_printers / detong_print_text / detong_print_qr。"
)

mcp = FastMCP(
    "hp-printer",
    instructions=(
        _HP_VS_DETONG
        + " 默认工具：hp_print_file、hp_preview_print、hp_scan_to_file、hp_get_status、hp_cancel_job。"
        " 排版不确定时先 hp_preview_print（不出纸），再 hp_print_file。"
        " 发现/队列/墨量/复印等需设置 HP_MCP_EXTRA_TOOLS=1。"
    ),
)


def _extra_tools() -> bool:
    raw = os.getenv("HP_MCP_EXTRA_TOOLS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@mcp.tool(name="hp_print_file")
async def hp_print_file(
    file_path: Optional[str] = None,
    content_base64: Optional[str] = None,
    filename: Optional[str] = None,
    url: Optional[str] = None,
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    page_range: str = "all",
    borderless: bool = False,
    printer_name: Optional[str] = None,
) -> dict:
    """【HP Smart Tank 750】经 IPP 打印办公文档（PDF/图/文本）。不是德佟标签机。

    禁止打热敏标签；标签用 detong_print_text / detong_print_qr。
    三选一：file_path 或 content_base64+filename 或 url。
    多页会合成一个 image/pwg-raster 作业，因此双面和多份是逐份的，并返回一个 job_id。
    横版内容会转进竖向走纸，因为这台机器只接受 portrait。
    排版不确定时先用 hp_preview_print（参数相同，不出纸）看阅读方向预览，再调用本工具。

    paper: A4、A5、A6、Letter、Legal、4x6、Hagaki、L、2L、DL、C6 等，以打印机为准。
    paper_type: plain、lightweight、photo、matte、brochure 等，映射到 IPP media-type。
    borderless: true 时四边距为 0。
    duplex: none | long_edge | short_edge
    color: color | monochrome | auto | auto-monochrome
    """
    settings = load_settings()
    return run_print_file(
        settings,
        file_path=file_path,
        content_base64=content_base64,
        filename=filename,
        url=url,
        copies=copies,
        orientation=orientation,
        paper=paper,
        paper_type=paper_type,
        quality=quality,
        color=color,
        duplex=duplex,
        page_range=page_range,
        borderless=borderless,
        printer_name=printer_name,
    )


@mcp.tool(name="hp_preview_print")
async def hp_preview_print(
    file_path: Optional[str] = None,
    content_base64: Optional[str] = None,
    filename: Optional[str] = None,
    url: Optional[str] = None,
    copies: int = 1,
    orientation: str = "portrait",
    paper: str = "A4",
    paper_type: str = "plain",
    quality: str = "normal",
    color: str = "color",
    duplex: str = "none",
    page_range: str = "all",
    borderless: bool = False,
    max_pages: int = 6,
    show_margins: bool = True,
    printer_name: Optional[str] = None,
) -> dict | list:
    """【HP Smart Tank 750】打印预览，不出纸。不是德佟标签机。

    用和 hp_print_file 相同的光栅排版生成阅读方向图片，给 agent 检查换行、页边和横版。
    参数与 hp_print_file 一致。确认后再调用 hp_print_file。
    返回的图片与 data.pages 顺序一致。淡红边和红色虚线是约 2.96 mm 不可印区域，不会印出来。
    横版按阅读方向显示；出纸时会转进竖向走纸。max_pages 默认 6，最多 8。
    """
    settings = load_settings()
    return run_preview_print(
        settings,
        file_path=file_path,
        content_base64=content_base64,
        filename=filename,
        url=url,
        copies=copies,
        orientation=orientation,
        paper=paper,
        paper_type=paper_type,
        quality=quality,
        color=color,
        duplex=duplex,
        page_range=page_range,
        borderless=borderless,
        max_pages=max_pages,
        show_margins=show_margins,
        printer_name=printer_name,
    ).as_tool_result()


@mcp.tool(name="hp_scan_to_file")
async def hp_scan_to_file(
    source: str = "Platen",
    dpi: int = 300,
    format: str = "pdf",
    color_mode: str = "RGB24",
    paper: str = "A4",
    orientation: str = "portrait",
    output_path: Optional[str] = None,
    include_base64: Optional[bool] = None,
) -> dict:
    """【HP Smart Tank 750】平板或 ADF 扫描为 PDF/JPEG。不是德佟标签机。

    source: Platen（稿台）或 Feeder/ADF。纸张、dpi、格式和颜色会按该扫描源的 eSCL 能力校验。
    稿台最高 1200 dpi，ADF 最高 300 dpi。设备不支持 PNG。
    color_mode: RGB24、Grayscale8、BlackAndWhite1。
    """
    settings = load_settings()
    return run_scan_to_file(
        settings,
        source=source,
        dpi=dpi,
        format=format,
        color_mode=color_mode,
        paper=paper,
        orientation=orientation,
        output_path=output_path,
        include_base64=include_base64,
    )


@mcp.tool(name="hp_get_status")
async def hp_get_status() -> dict:
    """【HP Smart Tank 750】主机是否可达、IPP 打印状态、eSCL 扫描状态。

    不是 detong_get_status（那是德佟标签机 / dtpweb）。
    """
    settings = load_settings()
    return run_get_device_status(
        settings,
        scanner_status_fn=run_get_scanner_status,
        print_queue_count_fn=print_queue_count,
        printer_ready_fn=lambda s: is_printer_ready(s),
        ipp_state_fn=get_ipp_printer_state,
    )


@mcp.tool(name="hp_cancel_job")
async def hp_cancel_job(job_id: int, printer_name: Optional[str] = None) -> dict:
    """【HP Smart Tank 750】按 IPP job_id 取消打印任务（通常来自 hp_print_file 返回值）。

    不是 detong_close。查历史队列请开 HP_MCP_EXTRA_TOOLS 后用 hp_list_jobs。
    """
    settings = load_settings()
    return run_cancel_print_job(settings, job_id=job_id, printer_name=printer_name)


if _extra_tools():

    @mcp.tool(name="hp_discover_printer")
    async def hp_discover_printer(timeout_sec: float = 5.0) -> dict:
        """【HP】mDNS 发现并探测 HP_PRINTER_HOST。IP 已固定时一般不用。"""
        settings = load_settings()
        return run_discover_printer(settings, timeout_sec=timeout_sec)

    @mcp.tool(name="hp_list_jobs")
    async def hp_list_jobs(printer_name: Optional[str] = None) -> dict:
        """【HP Smart Tank 750】列出 IPP 打印队列。"""
        settings = load_settings()
        return run_list_print_jobs(settings, printer_name=printer_name)

    @mcp.tool(name="hp_get_scan_capabilities")
    async def hp_get_scan_capabilities() -> dict:
        """【HP】eSCL 扫描能力（分辨率、格式、稿台/ADF）。"""
        settings = load_settings()
        return run_get_scan_capabilities(settings)

    @mcp.tool(name="hp_get_scanner_status")
    async def hp_get_scanner_status() -> dict:
        """【HP】eSCL 扫描头空闲/忙、ADF 是否有纸。日常用 hp_get_status 即可。"""
        settings = load_settings()
        return run_get_scanner_status(settings)

    @mcp.tool(name="hp_get_supply_levels")
    async def hp_get_supply_levels() -> dict:
        """【HP】墨量（EWS/SNMP/IPP，尽力而为）。"""
        settings = load_settings()
        return run_get_supply_levels(settings)

    @mcp.tool(name="hp_copy_document")
    async def hp_copy_document(
        source: str = "Platen",
        copies: int = 1,
        orientation: str = "portrait",
        paper: str = "A4",
        paper_type: str = "plain",
        quality: str = "normal",
        color: str = "color",
        duplex: str = "none",
        dpi: int = 300,
        format: str = "pdf",
    ) -> dict:
        """【HP】软件复印：先扫描再 IPP 打印。不是德佟标签。"""
        settings = load_settings()
        return run_copy_document(
            settings,
            source=source,
            copies=copies,
            orientation=orientation,
            paper=paper,
            paper_type=paper_type,
            quality=quality,
            color=color,
            duplex=duplex,
            dpi=dpi,
            format=format,
        )
