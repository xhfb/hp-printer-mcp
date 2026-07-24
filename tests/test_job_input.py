from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from hp_printer_mcp.config import Settings
from hp_printer_mcp.job_input import JobInputError, resolve_print_input


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        printer_host="192.168.31.11",
        printer_name="HP",
        scan_output_dir=tmp_path / "output",
        use_https=False,
        snmp_community="public",
        allowed_paths=[tmp_path],
        escl_timeout_sec=5,
        scan_poll_interval_sec=0.2,
        scan_poll_max_sec=5,
        ipp_uri="ipp://192.168.31.11:631/ipp/print",
        ipp_username="guest",
        ipp_password="",
        http_trust_env=False,
        max_upload_mb=1,
        job_tmp_dir=tmp_path / "jobs",
        job_tmp_ttl_sec=60,
        allow_remote_url=True,
        url_allow_rfc1918_only=True,
        include_scan_base64=True,
    )


def test_resolve_content_base64(tmp_path: Path):
    settings = _settings(tmp_path)
    payload = b"hello print"
    path, job_dir = resolve_print_input(
        settings,
        content_base64=base64.b64encode(payload).decode(),
        filename="hello.txt",
    )
    assert path.read_bytes() == payload
    assert job_dir.exists()


def test_resolve_requires_exactly_one_source(tmp_path: Path):
    settings = _settings(tmp_path)
    with pytest.raises(JobInputError):
        resolve_print_input(settings)
    with pytest.raises(JobInputError):
        resolve_print_input(
            settings,
            file_path="a.txt",
            content_base64="YQ==",
            filename="a.txt",
        )


def test_resolve_file_path(tmp_path: Path):
    settings = _settings(tmp_path)
    src = tmp_path / "doc.txt"
    src.write_text("page", encoding="utf-8")
    path, _job = resolve_print_input(settings, file_path=str(src))
    assert path.read_text(encoding="utf-8") == "page"


def test_reject_public_url_when_rfc1918_only(tmp_path: Path):
    settings = _settings(tmp_path)
    with pytest.raises(JobInputError):
        resolve_print_input(settings, url="https://example.com/a.pdf")
