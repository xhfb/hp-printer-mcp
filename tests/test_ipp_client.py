from __future__ import annotations

from hp_printer_mcp.ipp_client import (
    OP_GET_PRINTER_ATTRIBUTES,
    TAG_CHARSET,
    TAG_KEYWORD,
    TAG_NATURAL_LANGUAGE,
    TAG_URI,
    build_request,
    http_url_from_ipp_uri,
    parse_response,
)


def test_http_url_from_ipp_uri_default_port():
    assert (
        http_url_from_ipp_uri("ipp://192.168.31.11/ipp/print")
        == "http://192.168.31.11:631/ipp/print"
    )


def test_build_and_parse_roundtrip_status():
    # Minimal successful response: version + status + request-id + end tag
    # We only unit-test request builder shape and parse of a tiny buffer.
    body = build_request(
        OP_GET_PRINTER_ATTRIBUTES,
        request_id=7,
        operation_attributes=[
            (TAG_CHARSET, "attributes-charset", "utf-8"),
            (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
            (TAG_URI, "printer-uri", "ipp://192.168.31.11/ipp/print"),
            (TAG_KEYWORD, "requested-attributes", "printer-state"),
        ],
    )
    assert body[:2] == b"\x02\x00"
    assert body[2:4] == b"\x00\x0b"
    assert int.from_bytes(body[4:8], "big") == 7

    # Fake OK response with one integer attribute printer-state=3
    import struct

    raw = bytearray()
    raw += struct.pack(">BBHI", 2, 0, 0x0000, 7)
    raw.append(0x01)  # operation attributes
    raw.append(0x21)  # integer
    name = b"printer-state"
    raw += struct.pack(">H", len(name)) + name
    raw += struct.pack(">H", 4) + struct.pack(">i", 3)
    raw.append(0x03)
    parsed = parse_response(bytes(raw))
    assert parsed.ok
    assert parsed.first("printer-state") == 3
