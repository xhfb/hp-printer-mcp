from __future__ import annotations

from typing import Any

from hp_printer_mcp.config import Settings
from hp_printer_mcp.print_ipp import print_file
from hp_printer_mcp.scan_escl import scan_to_file


def copy_document(
    settings: Settings,
    *,
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
) -> dict[str, Any]:
    scan_result = scan_to_file(
        settings,
        source=source,
        dpi=dpi,
        format=format,
        color_mode="RGB24" if color == "color" else "Grayscale8",
        paper=paper,
        orientation=orientation,
        include_base64=False,
    )
    if not scan_result.get("success"):
        return scan_result

    scanned_path = scan_result["data"]["output_path"]
    print_result = print_file(
        settings,
        file_path=scanned_path,
        copies=copies,
        orientation=orientation,
        paper=paper,
        paper_type=paper_type,
        quality=quality,
        color=color,
        duplex=duplex,
    )
    if not print_result.get("success"):
        return print_result

    return {
        "success": True,
        "error": None,
        "data": {
            "scanned_file": scanned_path,
            "copies": copies,
            "print": print_result["data"],
        },
    }
