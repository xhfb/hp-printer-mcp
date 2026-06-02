from __future__ import annotations

import re
import socket
import struct
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from hp_printer_mcp.config import Settings, fail, ok

SUPPLY_LEVEL_OID = "1.3.6.1.2.1.43.11.1.1.9"
SUPPLY_MAX_OID = "1.3.6.1.2.1.43.11.1.1.8"
SUPPLY_DESC_OID = "1.3.6.1.2.1.43.11.1.1.6"


def _percent(level: int | None, maximum: int | None) -> int | None:
    if level is None or maximum in (None, 0, -2, -3):
        return None
    if level < 0:
        return None
    return max(0, min(100, round(level / maximum * 100)))


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_hp_ews_xml(text: str) -> list[dict[str, Any]]:
    supplies: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return supplies

    for elem in root.iter():
        if _local_tag(elem.tag) != "ConsumableInfo":
            continue
        label = None
        family = None
        ctype = None
        percent = None
        for child in elem.iter():
            child_tag = _local_tag(child.tag)
            text_val = (child.text or "").strip()
            if not text_val:
                continue
            if child_tag == "ConsumableLabelCode":
                label = text_val
            elif child_tag == "ConsumableFamilyName":
                family = text_val
            elif child_tag == "ConsumableTypeEnum":
                ctype = text_val
            elif child_tag == "ConsumablePercentageLevelRemaining":
                try:
                    percent = int(text_val)
                except ValueError:
                    pass
        if percent is None:
            continue
        parts = [p for p in (ctype, label or family) if p]
        name = " ".join(parts) if parts else "Unknown"
        supplies.append(
            {
                "name": name,
                "level": percent,
                "max_capacity": 100,
                "percent": max(0, min(100, percent)),
                "source": "hp_ews",
            }
        )

    if supplies:
        return supplies

    for elem in root.iter():
        tag = _local_tag(elem.tag)
        if tag.lower() not in ("consumable", "supply", "marker"):
            continue
        name = None
        level = None
        max_cap = None
        for child in elem.iter():
            child_tag = _local_tag(child.tag)
            text_val = (child.text or "").strip()
            if not text_val:
                continue
            ltag = child_tag.lower()
            if ltag in ("productname", "markername", "name", "description"):
                name = text_val
            elif ltag in ("level", "markerlevel", "currentlevel"):
                try:
                    level = int(text_val)
                except ValueError:
                    pass
            elif ltag in ("maxcapacity", "capacity", "maxlevel"):
                try:
                    max_cap = int(text_val)
                except ValueError:
                    pass
        if name or level is not None:
            supplies.append(
                {
                    "name": name or "Unknown",
                    "level": level,
                    "max_capacity": max_cap,
                    "percent": _percent(level, max_cap),
                    "source": "hp_ews",
                }
            )
    return supplies


def _fetch_hp_ews(settings: Settings) -> list[dict[str, Any]]:
    url = f"{settings.base_url}/DevMgmt/ConsumableConfigDyn.xml"
    with httpx.Client(timeout=settings.escl_timeout_sec, verify=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        supplies = _parse_hp_ews_xml(resp.text)
        if supplies:
            return supplies

        # Fallback: regex over ProductStatusDyn or similar pages
        alt = client.get(f"{settings.base_url}/DevMgmt/ProductStatusDyn.xml")
        if alt.status_code == 200:
            text = alt.text
            for match in re.finditer(
                r"(Black|Cyan|Magenta|Yellow)[^<]{0,40}?(\d{1,3})\s*%",
                text,
                re.IGNORECASE,
            ):
                supplies.append(
                    {
                        "name": match.group(1),
                        "level": None,
                        "max_capacity": None,
                        "percent": int(match.group(2)),
                        "source": "hp_ews_regex",
                    }
                )
    return supplies


def _snmp_walk(host: str, community: str, oid: str) -> list[tuple[str, int]]:
    try:
        from pysnmp.hlapi import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            nextCmd,
        )
    except ImportError:
        from pysnmp.hlapi.v1arch.asyncio import (  # type: ignore
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            next_cmd,
        )
        import asyncio

        async def _async_walk() -> list[tuple[str, int]]:
            results: list[tuple[str, int]] = []
            engine = SnmpEngine()
            transport = await UdpTransportTarget.create((host, 161))
            current_oid = ObjectType(ObjectIdentity(oid))
            while True:
                error_indication, error_status, _error_index, var_binds = await next_cmd(
                    engine,
                    CommunityData(community, mpModel=1),
                    transport,
                    ContextData(),
                    current_oid,
                )
                if error_indication or error_status or not var_binds:
                    break
                finished = False
                for name, val in var_binds:
                    oid_str = str(name)
                    if not oid_str.startswith(oid):
                        finished = True
                        break
                    try:
                        results.append((oid_str, int(val)))
                    except (TypeError, ValueError):
                        pass
                    current_oid = ObjectType(ObjectIdentity(oid_str))
                if finished:
                    break
            return results

        return asyncio.run(_async_walk())

    results: list[tuple[str, int]] = []
    for (
        error_indication,
        error_status,
        _error_index,
        var_binds,
    ) in nextCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        UdpTransportTarget((host, 161), timeout=3, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            break
        for name, val in var_binds:
            oid_str = str(name)
            if not oid_str.startswith(oid):
                return results
            try:
                results.append((oid_str, int(val)))
            except (TypeError, ValueError):
                pass
    return results


def _fetch_snmp(settings: Settings) -> list[dict[str, Any]]:
    host = settings.printer_host
    if host.startswith("http"):
        host = host.split("://", 1)[1]
    host = host.split("/")[0]

    try:
        levels = _snmp_walk(host, settings.snmp_community, SUPPLY_LEVEL_OID)
        maxes = {oid: val for oid, val in _snmp_walk(host, settings.snmp_community, SUPPLY_MAX_OID)}
        descs = {oid: val for oid, val in _snmp_walk(host, settings.snmp_community, SUPPLY_DESC_OID)}
    except Exception:
        return []

    supplies: list[dict[str, Any]] = []
    for oid, level in levels:
        suffix = oid.rsplit(".", 1)[-1]
        max_oid = f"{SUPPLY_MAX_OID}.{suffix}"
        desc_oid = f"{SUPPLY_DESC_OID}.{suffix}"
        maximum = maxes.get(max_oid)
        name = descs.get(desc_oid)
        supplies.append(
            {
                "name": str(name) if name is not None else f"Supply {suffix}",
                "level": level,
                "max_capacity": maximum,
                "percent": _percent(level, maximum),
                "source": "snmp",
            }
        )
    return supplies


def _ipp_attribute_read(data: bytes) -> dict[int, list[Any]]:
    attrs: dict[int, list[Any]] = {}
    if len(data) < 8:
        return attrs
    offset = 8
    current_group = 0x01

    def read_value(tag: int, buf: bytes, pos: int) -> tuple[Any, int]:
        if tag in (0x21, 0x23):
            if pos + 4 > len(buf):
                return None, pos
            return struct.unpack(">I", buf[pos : pos + 4])[0], pos + 4
        if tag in (0x30, 0x31, 0x34, 0x35):
            if pos + 2 > len(buf):
                return None, pos
            length = struct.unpack(">H", buf[pos : pos + 2])[0]
            pos += 2
            value = buf[pos : pos + length]
            pos += length
            if tag in (0x30, 0x31):
                return value.decode("utf-8", errors="replace"), pos
            return value, pos
        if tag == 0x00:
            return None, pos
        return None, pos

    while offset < len(data):
        tag = data[offset]
        offset += 1
        if tag in (0x01, 0x02, 0x04, 0x05):
            current_group = tag
            continue
        if tag == 0x03:
            break
        if offset + 2 > len(data):
            break
        name_len = struct.unpack(">H", data[offset : offset + 2])[0]
        offset += 2
        if name_len:
            offset += name_len
        if offset >= len(data):
            break
        value_tag = data[offset]
        offset += 1
        if offset + 2 > len(data):
            break
        offset += 2
        value, offset = read_value(value_tag, data, offset)
        if value is not None:
            attrs.setdefault(current_group, []).append(value)
    return attrs


def _fetch_ipp(settings: Settings) -> list[dict[str, Any]]:
    host = settings.printer_host
    if host.startswith("http"):
        host = host.split("://", 1)[1]
    host = host.split("/")[0]

    payload = (
        b"\x02\x00"
        b"\x00\x0b"
        b"\x00\x00\x00\x01"
        b"\x01"
        b"\x47"
        b"\x00\x12"
        b"attributes-charset"
        b"\x00\x05"
        b"utf-8"
        b"\x48"
        b"\x00\x1b"
        b"attributes-natural-language"
        b"\x00\x02"
        b"en"
        b"\x45"
        b"\x00\x0b"
        b"printer-uri"
        b"\x00\x1b"
        + f"ipp://{host}/ipp/print".encode("utf-8")
        + b"\x02"
        b"\x44"
        b"\x00\x14"
        b"requested-attributes"
        b"\x00\x0c"
        b"marker-levels"
        b"\x44"
        b"\x00\x14"
        b"requested-attributes"
        b"\x00\x0c"
        b"marker-names"
        b"\x03"
    )

    supplies: list[dict[str, Any]] = []
    with socket.create_connection((host, 631), timeout=settings.escl_timeout_sec) as sock:
        sock.sendall(
            b"POST /ipp/print HTTP/1.1\r\n"
            b"Content-Type: application/ipp\r\n"
            + f"Host: {host}\r\n".encode()
            + f"Content-Length: {len(payload)}\r\n\r\n".encode()
            + payload
        )
        response = sock.recv(65535)

    body = response.split(b"\r\n\r\n", 1)[-1]
    attrs = _ipp_attribute_read(body)
    names = [v.decode() if isinstance(v, bytes) else str(v) for v in attrs.get(0x04, []) if isinstance(v, (str, bytes))]
    levels = attrs.get(0x04, [])

    marker_levels = []
    marker_names = []
    for val in levels:
        if isinstance(val, int):
            marker_levels.append(val)
        elif isinstance(val, str) and val not in ("marker-levels", "marker-names"):
            marker_names.append(val)

    if not marker_names:
        marker_names = names

    for idx, level in enumerate(marker_levels):
        name = marker_names[idx] if idx < len(marker_names) else f"Marker {idx + 1}"
        percent = level if 0 <= level <= 100 else None
        supplies.append(
            {
                "name": name,
                "level": level,
                "max_capacity": 100 if percent is not None else None,
                "percent": percent,
                "source": "ipp",
            }
        )
    return supplies


def get_supply_levels(settings: Settings) -> dict[str, Any]:
    if not settings.printer_host:
        return fail("HP_PRINTER_HOST is not configured")

    errors: list[str] = []
    for fetcher_name, fetcher in (
        ("hp_ews", _fetch_hp_ews),
        ("snmp", _fetch_snmp),
        ("ipp", _fetch_ipp),
    ):
        try:
            supplies = fetcher(settings)
            if supplies:
                return ok({"supplies": supplies, "source": fetcher_name})
        except Exception as exc:
            errors.append(f"{fetcher_name}: {exc}")

    return fail(
        "Unable to read supply levels via HP EWS, SNMP, or IPP. "
        "For Smart Tank models, verify ink visually through the tank window.",
        data={"errors": errors},
    )
