import xml.etree.ElementTree as ET
from unittest.mock import patch

import httpx
import pytest

from hp_printer_mcp.config import load_settings
from hp_printer_mcp.scan_escl import (
    _build_scan_settings_xml,
    get_scan_capabilities,
    get_scanner_status,
    scan_region_for_paper,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HP_PRINTER_HOST", "192.168.1.50")
    monkeypatch.setenv("HP_SCAN_OUTPUT_DIR", str(tmp_path / "output"))
    return load_settings()


CAPABILITIES_XML = """<?xml version="1.0"?>
<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
  xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <scan:SettingProfiles>
    <scan:SettingProfile>
      <scan:DocumentFormats>
        <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
        <pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>
      </scan:DocumentFormats>
      <scan:SupportedResolutions>
        <scan:DiscreteResolutions>
          <scan:DiscreteResolution>
            <scan:XResolution>300</scan:XResolution>
            <scan:YResolution>300</scan:YResolution>
          </scan:DiscreteResolution>
        </scan:DiscreteResolutions>
      </scan:SupportedResolutions>
      <scan:ColorSpaces>
        <scan:ColorSpace>RGB24</scan:ColorSpace>
      </scan:ColorSpaces>
    </scan:SettingProfile>
  </scan:SettingProfiles>
  <scan:Platen>
    <scan:PlatenInputCaps>
      <scan:InputSource>Platen</scan:InputSource>
    </scan:PlatenInputCaps>
  </scan:Platen>
  <scan:Adf>
    <scan:AdfInputCaps>
      <scan:InputSource>Feeder</scan:InputSource>
    </scan:AdfInputCaps>
  </scan:Adf>
</scan:ScannerCapabilities>"""

STATUS_XML = """<?xml version="1.0"?>
<scan:ScannerStatus xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <scan:ScannerState>Idle</scan:ScannerState>
  <scan:AdfState>Loaded</scan:AdfState>
</scan:ScannerStatus>"""


def test_build_scan_settings_xml():
    payload = _build_scan_settings_xml(
        source="Adf",
        dpi=600,
        color_mode="Grayscale8",
        mime_type="application/pdf",
        paper="A4",
    )
    root = ET.fromstring(payload)
    assert root is not None
    text_blob = ET.tostring(root, encoding="unicode")
    assert "Feeder" in text_blob
    assert "600" in text_blob
    assert "Grayscale8" in text_blob
    assert "ScanRegion" in text_blob
    assert "2480" in text_blob
    assert "3508" in text_blob


def test_scan_region_b5():
    assert scan_region_for_paper("B5") == (2079, 2953)


def test_build_scan_settings_max_area():
    payload = _build_scan_settings_xml(
        source="Platen",
        dpi=300,
        color_mode="RGB24",
        mime_type="application/pdf",
        paper="MAX",
    )
    text_blob = ET.tostring(ET.fromstring(payload), encoding="unicode")
    assert "ScanRegion" not in text_blob


def test_get_scan_capabilities_mock(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ScannerCapabilities")
        return httpx.Response(200, text=CAPABILITIES_XML)

    transport = httpx.MockTransport(handler)
    with patch("hp_printer_mcp.scan_escl._client") as mock_client:
        mock_client.return_value.__enter__.return_value = httpx.Client(transport=transport)
        result = get_scan_capabilities(settings)

    assert result["success"] is True
    assert {"x": 300, "y": 300} in result["data"]["resolutions"]
    assert "application/pdf" in result["data"]["document_formats"]


def test_get_scanner_status_mock(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ScannerStatus")
        return httpx.Response(200, text=STATUS_XML)

    transport = httpx.MockTransport(handler)
    with patch("hp_printer_mcp.scan_escl._client") as mock_client:
        mock_client.return_value.__enter__.return_value = httpx.Client(transport=transport)
        result = get_scanner_status(settings)

    assert result["success"] is True
    assert result["data"]["scanner_state"] == "Idle"
    assert result["data"]["is_idle"] is True


def test_load_settings_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HP_PRINTER_HOST", "10.0.0.5")
    monkeypatch.delenv("HP_SCAN_OUTPUT_DIR", raising=False)
    settings = load_settings()
    assert settings.printer_host == "10.0.0.5"
    assert settings.escl_base == "http://10.0.0.5/eSCL"


def test_settings_path_guard(settings, tmp_path):
    allowed = tmp_path / "output"
    allowed.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(PermissionError):
        settings.ensure_allowed_path(outside, for_write=False)
