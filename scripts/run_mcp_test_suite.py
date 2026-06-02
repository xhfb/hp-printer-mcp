#!/usr/bin/env python3
"""Run hp-printer MCP integration tests against a live device.

Usage (from repo root):
  python scripts/run_mcp_test_suite.py

Set HP_SCAN_POLL_MAX_SEC=900 for multi-page ADF scans.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Repo src on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("HP_SCAN_POLL_MAX_SEC", "900")

from hp_printer_mcp.config import load_settings  # noqa: E402
from hp_printer_mcp.copy import copy_document  # noqa: E402
from hp_printer_mcp.discovery import discover_printer, get_device_status  # noqa: E402
from hp_printer_mcp.print_win32 import (  # noqa: E402
    cancel_print_job,
    is_printer_ready,
    list_print_jobs,
    print_file,
    print_queue_count,
)
from hp_printer_mcp.scan_escl import (  # noqa: E402
    get_scan_capabilities,
    get_scanner_status,
    scan_to_file,
)
from hp_printer_mcp.supplies import get_supply_levels  # noqa: E402


@dataclass
class Case:
    id: str
    name: str
    fn: Callable[[], dict[str, Any]]
    skip: bool = False
    skip_reason: str = ""


@dataclass
class RunReport:
    started: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    cases: list[dict[str, Any]] = field(default_factory=list)

    def add(self, case: Case, result: dict[str, Any] | None, error: str | None, elapsed: float) -> None:
        self.cases.append(
            {
                "id": case.id,
                "name": case.name,
                "skipped": case.skip,
                "skip_reason": case.skip_reason,
                "success": None if case.skip else (result or {}).get("success"),
                "error": error or (None if case.skip else (result or {}).get("error")),
                "elapsed_sec": round(elapsed, 2),
                "data_summary": _summarize(result) if result and not case.skip else None,
            }
        )


def _summarize(result: dict[str, Any] | None) -> Any:
    if not result or not result.get("success"):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return data
    keys = (
        "output_path",
        "page_count",
        "paper",
        "scanner_state",
        "adf_state",
        "is_idle",
        "printer_ready",
        "jobs",
        "supplies",
        "hosts",
        "file_path",
    )
    return {k: data[k] for k in keys if k in data}


def _wait_scanner_idle(settings, timeout_sec: float = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = get_scanner_status(settings)
        if last.get("success") and last["data"].get("is_idle"):
            return last
        time.sleep(3)
    return last


def main() -> int:
    settings = load_settings()
    out_dir = settings.scan_output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_pdf = out_dir / "scan_20260603_005206.pdf"
    welcome_pdf = out_dir / "welcome.pdf"
    welcome_txt = out_dir / "welcome.txt"
    welcome_png = out_dir / "hp_smart_dashboard.png"
    docx_files = list(out_dir.glob("MinerU_MCP*.docx"))
    docx_path = docx_files[0] if docx_files else None
    docs_pdf = Path.home() / "Documents"
    feasibility = next(docs_pdf.glob("*可行性研究报告2025-12.pdf"), None)

    cases: list[Case] = [
        Case("T01", "discover_printer", lambda: discover_printer(settings, timeout_sec=5)),
        Case(
            "T02",
            "get_device_status",
            lambda: get_device_status(
                settings,
                scanner_status_fn=get_scanner_status,
                print_queue_count_fn=print_queue_count,
                printer_ready_fn=lambda s: is_printer_ready(s),
            ),
        ),
        Case("T03", "get_scan_capabilities", lambda: get_scan_capabilities(settings)),
        Case("T04", "get_supply_levels", lambda: get_supply_levels(settings)),
        Case("T05", "get_scanner_status (ADF loaded)", lambda: get_scanner_status(settings)),
        # --- already verified in session ---
        Case("T06", "scan ADF B5 PDF", lambda: {"success": True, "data": {"skipped": True}}, skip=True, skip_reason="已验证"),
        Case("T07", "print PDF B5 color long_edge", lambda: {"success": True, "data": {"skipped": True}}, skip=True, skip_reason="已验证"),
        Case("T08", "print PDF page_range 1-4", lambda: {"success": True, "data": {"skipped": True}}, skip=True, skip_reason="已验证"),
        Case(
            "T10",
            "scan ADF paper=MAX",
            lambda: {"success": True, "data": {"skipped": True}},
            skip=True,
            skip_reason="会扫完 ADF 全部页，与 B5 测试重复，跳过",
        ),
        Case(
            "T10b",
            "scan Platen B5 PDF",
            lambda: {"success": True, "data": {"skipped": True}},
            skip=True,
            skip_reason="需人工将 1 张纸放到玻璃板，跳过",
        ),
        # --- print first (uses print tray, not ADF) ---
        Case(
            "T11",
            "print PNG B5 monochrome",
            lambda: print_file(
                settings,
                file_path=str(welcome_png),
                paper="B5",
                color="monochrome",
                duplex="none",
            )
            if welcome_png.exists()
            else fail_missing(welcome_png),
        ),
        Case(
            "T12",
            "print TXT B5",
            lambda: print_file(
                settings,
                file_path=str(welcome_txt),
                paper="B5",
                color="color",
                duplex="none",
            )
            if welcome_txt.exists()
            else fail_missing(welcome_txt),
        ),
        Case(
            "T13",
            "print PDF short_edge duplex",
            lambda: print_file(
                settings,
                file_path=str(welcome_pdf),
                paper="B5",
                color="color",
                duplex="short_edge",
            )
            if welcome_pdf.exists()
            else fail_missing(welcome_pdf),
        ),
        Case(
            "T14",
            "print PDF landscape",
            lambda: print_file(
                settings,
                file_path=str(welcome_pdf),
                paper="B5",
                orientation="landscape",
                duplex="none",
            )
            if welcome_pdf.exists()
            else fail_missing(welcome_pdf),
        ),
        Case(
            "T15",
            "print scanned PDF 1 page monochrome",
            lambda: print_file(
                settings,
                file_path=str(existing_pdf),
                paper="B5",
                color="monochrome",
                duplex="none",
                page_range="1",
            )
            if existing_pdf.exists()
            else fail_missing(existing_pdf),
        ),
        Case(
            "T16",
            "print DOCX direct (expect fail or driver print)",
            lambda: print_file(
                settings,
                file_path=str(docx_path),
                paper="B5",
                color="color",
                duplex="none",
            )
            if docx_path
            else {"success": False, "error": "docx not found", "data": None},
        ),
        Case("T17", "list_print_jobs", lambda: list_print_jobs(settings)),
        Case("T18", "cancel_print_job", lambda: _test_cancel_job(settings, welcome_pdf)),
        Case("T19", "print invalid path", lambda: _expect_fail_path(settings)),
        # --- ADF scan (consumes all sheets in feeder) ---
        Case(
            "T09",
            "scan ADF B5 JPEG (saves 1st page if multi)",
            lambda: scan_to_file(
                settings,
                source="ADF",
                paper="B5",
                dpi=300,
                format="jpeg",
                color_mode="RGB24",
                output_path=str(out_dir / "test_adf_b5.jpg"),
            ),
        ),
        # --- copy workflow (needs ADF paper again) ---
        Case(
            "T20",
            "copy_document ADF B5 1 copy simplex",
            lambda: copy_document(
                settings,
                source="ADF",
                paper="B5",
                color="color",
                duplex="none",
                dpi=300,
                format="pdf",
            ),
        ),
    ]

    report = RunReport()
    print(f"=== HP Printer MCP Test Suite ===\nHost: {settings.printer_host}\n")

    for case in cases:
        if case.skip:
            report.add(case, {"success": True, "data": {}}, None, 0)
            print(f"[SKIP] {case.id} {case.name} — {case.skip_reason}")
            continue

        print(f"[RUN ] {case.id} {case.name} ...", flush=True)
        t0 = time.time()
        result: dict[str, Any] | None = None
        err: str | None = None
        try:
            if case.id.startswith("T09") or case.id == "T20":
                st = get_scanner_status(settings)
                if not st.get("success"):
                    result = st
                elif not st["data"].get("is_idle"):
                    print("       waiting scanner idle...", flush=True)
                    _wait_scanner_idle(settings)
                elif case.id == "T20" and "empty" in str(st["data"].get("adf_state", "")).lower():
                    result = {
                        "success": False,
                        "error": "ADF empty before copy; reload paper for T20",
                        "data": None,
                    }
                else:
                    result = case.fn()
            else:
                result = case.fn()
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        elapsed = time.time() - t0
        report.add(case, result, err, elapsed)
        ok = result.get("success") if result and not err else False
        print(f"[{'PASS' if ok else 'FAIL'}] {case.id} ({elapsed:.1f}s)", flush=True)
        if not ok:
            print(f"       {(err or result.get('error') if result else 'unknown')}", flush=True)
        if case.id in ("T09", "T20"):
            _wait_scanner_idle(settings, timeout_sec=300)

    report_path = out_dir / f"mcp_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report.cases, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for c in report.cases if c.get("success") is True)
    failed = sum(1 for c in report.cases if c.get("success") is False)
    skipped = sum(1 for c in report.cases if c.get("skipped"))
    print(f"\n=== Done: pass={passed} fail={failed} skip={skipped} ===")
    print(f"Report: {report_path}")
    return 0 if failed == 0 else 1


def fail_missing(path: Path) -> dict[str, Any]:
    return {"success": False, "error": f"Missing file: {path}", "data": None}


def _expect_fail_path(settings) -> dict[str, Any]:
    try:
        settings.ensure_allowed_path(Path("C:/Windows/System32/notepad.exe"), for_write=False)
        return {"success": False, "error": "Expected PermissionError", "data": None}
    except PermissionError as exc:
        return {"success": True, "data": {"blocked": str(exc)}}


def _test_cancel_job(settings, welcome_pdf: Path) -> dict[str, Any]:
    if not welcome_pdf.exists():
        return fail_missing(welcome_pdf)
    import threading

    result: dict[str, Any] = {"success": False, "error": "timeout", "data": None}

    def _print():
        print_file(settings, file_path=str(welcome_pdf), paper="B5", duplex="none")

    t = threading.Thread(target=_print, daemon=True)
    t.start()
    time.sleep(2)
    listed = list_print_jobs(settings)
    if not listed.get("success") or not listed["data"]["jobs"]:
        return {"success": False, "error": "No job to cancel", "data": listed}
    job_id = listed["data"]["jobs"][0]["job_id"]
    cancelled = cancel_print_job(settings, job_id=job_id)
    result = cancelled
    t.join(timeout=30)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
