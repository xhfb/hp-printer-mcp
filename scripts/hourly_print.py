"""Generate and print an hourly report for HP Smart Tank 750."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.print_win32 import is_printer_ready, print_file


def _default_message() -> str:
    return "定时打印任务运行正常。可在 output/hourly_template.txt 中自定义内容。"


def _load_template(path: Path) -> str:
    if not path.is_file():
        return _default_message()
    text = path.read_text(encoding="utf-8")
    return text.strip() or _default_message()


def build_report(
    *,
    template_path: Path,
    settings,
) -> str:
    now = datetime.now()
    template = _load_template(template_path)
    printer_name = settings.printer_name or "（未配置）"
    ready = is_printer_ready(settings)
    status = "就绪" if ready else "离线或不可用"

    return template.format(
        datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M:%S"),
        printer_name=printer_name,
        printer_host=settings.printer_host or "（未配置）",
        printer_status=status,
        message=_default_message(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print hourly report to HP printer")
    parser.add_argument(
        "--template",
        default="output/hourly_template.txt",
        help="Template file path (relative to project root or absolute)",
    )
    parser.add_argument(
        "--output",
        default="output/hourly_report.txt",
        help="Generated report path before printing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate report file only, do not print",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    project_root = Path(__file__).resolve().parents[1]
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = (project_root / template_path).resolve()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(template_path=template_path, settings=settings)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")

    if args.dry_run:
        print("Dry run: skip printing")
        return 0

    result = print_file(settings, file_path=str(output_path))
    if not result.get("success"):
        print(result.get("error") or "Print failed", file=sys.stderr)
        return 1

    print(f"Printed to: {result['data']['printer_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
