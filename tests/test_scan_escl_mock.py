import xml.etree.ElementTree as ET
from io import BytesIO
from unittest.mock import patch

import fitz
import httpx
import pytest
from PIL import Image

from hp_printer_mcp.config import load_settings, ok
from hp_printer_mcp.scan_escl import (
    _build_scan_settings_xml,
    _merge_pdf_pages,
    get_scan_capabilities,
    get_scanner_status,
    parse_scanner_capabilities,
    scan_region_for_paper,
    scan_to_file,
    validate_scan_request,
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


def test_jpeg_scan_pdf_uses_scan_dpi_for_page_size():
    image = Image.new("RGB", (2480, 3508), "white")
    raw = BytesIO()
    image.save(raw, format="JPEG")
    payload = raw.getvalue()
    pdf = _merge_pdf_pages([payload, payload], dpi=300)
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        assert doc.page_count == 2
        assert doc[0].rect.width == pytest.approx(595.2, abs=0.2)
        assert doc[0].rect.height == pytest.approx(841.92, abs=0.2)
    finally:
        doc.close()


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


SPLIT_CAPS_XML = """<?xml version="1.0"?>
<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
  xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <scan:Platen>
    <scan:PlatenInputCaps>
      <scan:MinWidth>8</scan:MinWidth>
      <scan:MaxWidth>2550</scan:MaxWidth>
      <scan:MinHeight>8</scan:MinHeight>
      <scan:MaxHeight>3508</scan:MaxHeight>
      <scan:SettingProfiles>
        <scan:SettingProfile>
          <scan:ColorModes>
            <scan:ColorMode>BlackAndWhite1</scan:ColorMode>
            <scan:ColorMode>Grayscale8</scan:ColorMode>
            <scan:ColorMode>RGB24</scan:ColorMode>
          </scan:ColorModes>
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
              <scan:DiscreteResolution>
                <scan:XResolution>600</scan:XResolution>
                <scan:YResolution>600</scan:YResolution>
              </scan:DiscreteResolution>
            </scan:DiscreteResolutions>
          </scan:SupportedResolutions>
        </scan:SettingProfile>
      </scan:SettingProfiles>
    </scan:PlatenInputCaps>
  </scan:Platen>
  <scan:Adf>
    <scan:AdfSimplexInputCaps>
      <scan:MinWidth>900</scan:MinWidth>
      <scan:MaxWidth>2550</scan:MaxWidth>
      <scan:MinHeight>1500</scan:MinHeight>
      <scan:MaxHeight>4200</scan:MaxHeight>
      <scan:SettingProfiles>
        <scan:SettingProfile>
          <scan:ColorModes>
            <scan:ColorMode>RGB24</scan:ColorMode>
          </scan:ColorModes>
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
        </scan:SettingProfile>
      </scan:SettingProfiles>
    </scan:AdfSimplexInputCaps>
  </scan:Adf>
</scan:ScannerCapabilities>"""


def _split_caps() -> dict:
    return parse_scanner_capabilities(ET.fromstring(SPLIT_CAPS_XML))


def test_scan_rejects_png_adf_600_and_oversized_platen():
    caps = _split_caps()
    with pytest.raises(ValueError, match="image/png"):
        validate_scan_request(
            caps,
            source="Platen",
            dpi=300,
            format="png",
            color_mode="RGB24",
            paper="A4",
            orientation="portrait",
        )
    with pytest.raises(ValueError, match="Feeder does not support 600"):
        validate_scan_request(
            caps,
            source="ADF",
            dpi=600,
            format="pdf",
            color_mode="RGB24",
            paper="A4",
            orientation="portrait",
        )
    with pytest.raises(ValueError, match="taller than the Platen"):
        validate_scan_request(
            caps,
            source="Platen",
            dpi=300,
            format="pdf",
            color_mode="RGB24",
            paper="Legal",
            orientation="portrait",
        )
    checked = validate_scan_request(
        caps,
        source="Platen",
        dpi=600,
        format="pdf",
        color_mode="BlackAndWhite1",
        paper="A4",
        orientation="portrait",
    )
    assert checked["color_mode"] == "BlackAndWhite1"


def test_scan_to_file_warns_when_jpeg_drops_extra_pages(settings, tmp_path):
    caps = _split_caps()
    idle = ok({"scanner_state": "Idle", "adf_state": None, "adf_loaded": None, "is_idle": True})
    jpeg = b"\xff\xd8\xff\xd9"

    with (
        patch("hp_printer_mcp.scan_escl.get_scanner_status", return_value=idle),
        patch("hp_printer_mcp.scan_escl.get_scan_capabilities", return_value=ok(caps)),
        patch("hp_printer_mcp.scan_escl._create_scan_job", return_value="job-1"),
        patch("hp_printer_mcp.scan_escl._poll_scan_job", return_value=["http://printer/NextDocument"]),
        patch(
            "hp_printer_mcp.scan_escl._fetch_scan_pages_via_next_document",
            return_value=[jpeg, jpeg],
        ),
    ):
        result = scan_to_file(
            settings,
            source="Platen",
            dpi=300,
            format="jpeg",
            paper="A4",
            output_path=str(tmp_path / "output" / "scan.jpg"),
            include_base64=False,
        )

    assert result["success"] is True, result
    assert result["data"]["page_count"] == 2
    assert "only page 1" in " ".join(result["data"]["warnings"])
    assert (tmp_path / "output" / "scan.jpg").read_bytes() == jpeg


def test_settings_path_guard(settings, tmp_path):
    allowed = tmp_path / "output"
    allowed.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(PermissionError):
        settings.ensure_allowed_path(outside, for_write=False)
