from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

TAG_OPERATION_ATTRIBUTES = 0x01
TAG_JOB_ATTRIBUTES = 0x02
TAG_END_OF_ATTRIBUTES = 0x03
TAG_PRINTER_ATTRIBUTES = 0x04
TAG_UNSUPPORTED = 0x05

TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_RESOLUTION = 0x32
TAG_RANGE_OF_INTEGER = 0x33
TAG_BEGIN_COLLECTION = 0x34
TAG_END_COLLECTION = 0x37
TAG_TEXT_WITHOUT_LANG = 0x41
TAG_NAME_WITHOUT_LANG = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_NATURAL_LANGUAGE = 0x48
TAG_MIME_MEDIA_TYPE = 0x49
TAG_MEMBER_NAME = 0x4A

OP_PRINT_JOB = 0x0002
OP_VALIDATE_JOB = 0x0004
OP_CREATE_JOB = 0x0005
OP_SEND_DOCUMENT = 0x0006
OP_CANCEL_JOB = 0x0008
OP_GET_JOBS = 0x000A
OP_GET_PRINTER_ATTRIBUTES = 0x000B


@dataclass
class IppResponse:
    status_code: int
    request_id: int
    attributes: dict[str, list[Any]] = field(default_factory=dict)
    raw: bytes = b""

    @property
    def ok(self) -> bool:
        return 0x0000 <= self.status_code <= 0x00FF

    def first(self, name: str, default: Any = None) -> Any:
        values = self.attributes.get(name)
        if not values:
            return default
        return values[0]


class IppError(RuntimeError):
    def __init__(self, message: str, *, response: IppResponse | None = None):
        super().__init__(message)
        self.response = response


@dataclass(frozen=True)
class IppCollection:
    """IPP collection (RFC 3382). ``members`` are (value-tag, member-name, value)."""

    members: tuple[tuple[Any, ...], ...]


def http_url_from_ipp_uri(ipp_uri: str) -> str:
    parsed = urlparse(ipp_uri)
    scheme = "https" if parsed.scheme == "ipps" else "http"
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 631)
    path = parsed.path or "/ipp/print"
    return f"{scheme}://{host}:{port}{path}"


def _encode_value(tag: int, value: Any) -> bytes:
    if tag in (TAG_INTEGER, TAG_ENUM):
        return struct.pack(">i", int(value))
    if tag == TAG_BOOLEAN:
        return b"\x01" if value else b"\x00"
    if tag == TAG_RESOLUTION:
        x, y, units = value
        return struct.pack(">iiB", int(x), int(y), int(units))
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _write_attribute(buf: bytearray, tag: int, name: str, value: Any) -> None:
    """Append one IPP attribute. Collections are encoded per RFC 3382."""
    name_b = name.encode("utf-8") if name else b""
    if isinstance(value, IppCollection) or tag == TAG_BEGIN_COLLECTION:
        if not isinstance(value, IppCollection):
            raise TypeError("collection attribute value must be an IppCollection")
        buf.append(TAG_BEGIN_COLLECTION)
        buf += struct.pack(">H", len(name_b)) + name_b
        buf += struct.pack(">H", 0)
        for member_tag, member_name, member_value in value.members:
            member_b = str(member_name).encode("utf-8")
            buf.append(TAG_MEMBER_NAME)
            buf += struct.pack(">H", 0)
            buf += struct.pack(">H", len(member_b)) + member_b
            _write_attribute(buf, int(member_tag), "", member_value)
        buf.append(TAG_END_COLLECTION)
        buf += struct.pack(">H", 0)
        buf += struct.pack(">H", 0)
        return
    value_b = _encode_value(tag, value)
    buf.append(tag)
    buf += struct.pack(">H", len(name_b)) + name_b
    buf += struct.pack(">H", len(value_b)) + value_b


def build_request(
    operation: int,
    *,
    request_id: int = 1,
    operation_attributes: list[tuple[int, str, Any]] | None = None,
    job_attributes: list[tuple[int, str, Any]] | None = None,
    data: bytes = b"",
) -> bytes:
    buf = bytearray()
    buf += struct.pack(">BBHI", 2, 0, operation, request_id)

    def write_group(group_tag: int, attrs: list[tuple[int, str, Any]] | None) -> None:
        nonlocal buf
        if not attrs:
            return
        buf.append(group_tag)
        last_name = ""
        for tag, name, value in attrs:
            use_name = "" if name and name == last_name else name
            if name:
                last_name = name
            _write_attribute(buf, tag, use_name, value)

    write_group(TAG_OPERATION_ATTRIBUTES, operation_attributes)
    write_group(TAG_JOB_ATTRIBUTES, job_attributes)
    buf.append(TAG_END_OF_ATTRIBUTES)
    buf += data
    return bytes(buf)


def _decode_value(tag: int, raw: bytes) -> Any:
    if tag in (TAG_INTEGER, TAG_ENUM) and len(raw) == 4:
        return struct.unpack(">i", raw)[0]
    if tag == TAG_BOOLEAN and len(raw) == 1:
        return raw != b"\x00"
    if tag == TAG_RESOLUTION and len(raw) == 9:
        return struct.unpack(">iiB", raw)
    if tag == TAG_RANGE_OF_INTEGER and len(raw) == 8:
        return struct.unpack(">ii", raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw


_GROUP_TAGS = {
    TAG_OPERATION_ATTRIBUTES,
    TAG_JOB_ATTRIBUTES,
    TAG_PRINTER_ATTRIBUTES,
    TAG_UNSUPPORTED,
}


def _read_name_and_value(payload: bytes, offset: int) -> tuple[str, bytes, int]:
    if offset + 4 > len(payload):
        raise IppError("Truncated IPP attribute")
    name_len = struct.unpack_from(">H", payload, offset)[0]
    offset += 2
    if offset + name_len + 2 > len(payload):
        raise IppError("Truncated IPP attribute name")
    name = payload[offset : offset + name_len].decode("utf-8", errors="replace")
    offset += name_len
    value_len = struct.unpack_from(">H", payload, offset)[0]
    offset += 2
    if offset + value_len > len(payload):
        raise IppError("Truncated IPP attribute value")
    raw = payload[offset : offset + value_len]
    return name, raw, offset + value_len


def _store_member(dest: dict[str, Any], key: str, value: Any) -> None:
    if not key:
        return
    if key not in dest:
        dest[key] = value
        return
    current = dest[key]
    if isinstance(current, list):
        current.append(value)
    else:
        dest[key] = [current, value]


def _parse_collection(payload: bytes, offset: int) -> tuple[dict[str, Any], int]:
    members: dict[str, Any] = {}
    while offset < len(payload):
        start = offset
        tag = payload[offset]
        if tag == TAG_END_OF_ATTRIBUTES:
            break
        if tag == TAG_END_COLLECTION:
            offset += 1
            _name, _raw, offset = _read_name_and_value(payload, offset)
            break
        if tag == TAG_MEMBER_NAME:
            offset += 1
            name, raw, offset = _read_name_and_value(payload, offset)
            member_name = name or raw.decode("utf-8", errors="replace")
            if offset >= len(payload):
                raise IppError("Truncated IPP collection member")
            value_tag = payload[offset]
            offset += 1
            if value_tag == TAG_BEGIN_COLLECTION:
                _nested_name, _nested_raw, offset = _read_name_and_value(payload, offset)
                value, offset = _parse_collection(payload, offset)
            elif value_tag == TAG_END_COLLECTION:
                raise IppError("Unexpected end of IPP collection")
            else:
                value_name, value_raw, offset = _read_name_and_value(payload, offset)
                if value_name and not member_name:
                    member_name = value_name
                value = _decode_value(value_tag, value_raw)
            _store_member(members, member_name, value)
        else:
            # Some stacks put the member name on the value tag itself.
            offset += 1
            name, raw, offset = _read_name_and_value(payload, offset)
            if tag == TAG_BEGIN_COLLECTION:
                value, offset = _parse_collection(payload, offset)
            else:
                value = _decode_value(tag, raw)
            _store_member(members, name, value)
        if offset == start:
            raise IppError("IPP collection parser made no progress")
    return members, offset


def parse_response(payload: bytes) -> IppResponse:
    if len(payload) < 8:
        raise IppError(f"IPP response too short ({len(payload)} bytes)")

    _maj, _min, status_code, request_id = struct.unpack(">BBHI", payload[:8])
    attrs: dict[str, list[Any]] = {}
    offset = 8
    current_name = ""

    while offset < len(payload):
        tag = payload[offset]
        offset += 1
        if tag == TAG_END_OF_ATTRIBUTES:
            break
        if tag in _GROUP_TAGS:
            current_name = ""
            continue
        if tag == TAG_BEGIN_COLLECTION:
            name, _raw, offset = _read_name_and_value(payload, offset)
            value, offset = _parse_collection(payload, offset)
        elif tag == TAG_END_COLLECTION:
            _name, _raw, offset = _read_name_and_value(payload, offset)
            continue
        else:
            name, raw, offset = _read_name_and_value(payload, offset)
            value = _decode_value(tag, raw)
        if name:
            current_name = name
        elif not current_name:
            continue
        attrs.setdefault(current_name, []).append(value)

    return IppResponse(
        status_code=status_code,
        request_id=request_id,
        attributes=attrs,
        raw=payload,
    )


class IppClient:
    def __init__(
        self,
        *,
        ipp_uri: str,
        client: httpx.Client,
        username: str = "guest",
        password: str = "",
    ) -> None:
        self.ipp_uri = ipp_uri
        self.http_url = http_url_from_ipp_uri(ipp_uri)
        self.client = client
        self.auth = httpx.DigestAuth(username, password)
        self._request_id = 1

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def request(
        self,
        operation: int,
        *,
        operation_attributes: list[tuple[int, str, Any]] | None = None,
        job_attributes: list[tuple[int, str, Any]] | None = None,
        data: bytes = b"",
    ) -> IppResponse:
        body = build_request(
            operation,
            request_id=self._next_id(),
            operation_attributes=operation_attributes,
            job_attributes=job_attributes,
            data=data,
        )
        resp = self.client.post(
            self.http_url,
            content=body,
            headers={"Content-Type": "application/ipp"},
            auth=self.auth,
        )
        resp.raise_for_status()
        parsed = parse_response(resp.content)
        if not parsed.ok:
            message = parsed.first("status-message") or parsed.first(
                "detailed-status-message"
            )
            raise IppError(
                f"IPP operation 0x{operation:04x} failed: "
                f"status=0x{parsed.status_code:04x}"
                + (f" ({message})" if message else ""),
                response=parsed,
            )
        return parsed

    def get_printer_attributes(self, requested: list[str] | None = None) -> IppResponse:
        attrs: list[tuple[int, str, Any]] = [
            (TAG_CHARSET, "attributes-charset", "utf-8"),
            (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
            (TAG_URI, "printer-uri", self.ipp_uri),
        ]
        names = requested or ["all"]
        for i, name in enumerate(names):
            attrs.append((TAG_KEYWORD, "requested-attributes" if i == 0 else "", name))
        return self.request(OP_GET_PRINTER_ATTRIBUTES, operation_attributes=attrs)

    def print_job(
        self,
        document: bytes,
        *,
        document_format: str,
        job_name: str = "hp-printer-mcp",
        copies: int = 1,
        sides: str = "one-sided",
        media: str | None = None,
        media_col: IppCollection | None = None,
        print_color_mode: str | None = None,
        print_quality: int | None = None,
        print_scaling: str | None = None,
        orientation_requested: int | None = None,
    ) -> IppResponse:
        return self._submit_document(
            OP_PRINT_JOB,
            document,
            document_format=document_format,
            job_name=job_name,
            copies=copies,
            sides=sides,
            media=media,
            media_col=media_col,
            print_color_mode=print_color_mode,
            print_quality=print_quality,
            print_scaling=print_scaling,
            orientation_requested=orientation_requested,
        )

    def validate_job(
        self,
        document: bytes,
        *,
        document_format: str,
        job_name: str = "hp-printer-mcp",
        copies: int = 1,
        sides: str = "one-sided",
        media: str | None = None,
        media_col: IppCollection | None = None,
        print_color_mode: str | None = None,
        print_quality: int | None = None,
        print_scaling: str | None = None,
        orientation_requested: int | None = None,
    ) -> IppResponse:
        """Validate-Job (0x0004). Does not create a job and does not print."""
        return self._submit_document(
            OP_VALIDATE_JOB,
            document,
            document_format=document_format,
            job_name=job_name,
            copies=copies,
            sides=sides,
            media=media,
            media_col=media_col,
            print_color_mode=print_color_mode,
            print_quality=print_quality,
            print_scaling=print_scaling,
            orientation_requested=orientation_requested,
        )

    def _submit_document(
        self,
        operation: int,
        document: bytes,
        *,
        document_format: str,
        job_name: str,
        copies: int,
        sides: str,
        media: str | None,
        media_col: IppCollection | None,
        print_color_mode: str | None,
        print_quality: int | None,
        print_scaling: str | None,
        orientation_requested: int | None,
    ) -> IppResponse:
        op_attrs: list[tuple[int, str, Any]] = [
            (TAG_CHARSET, "attributes-charset", "utf-8"),
            (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
            (TAG_URI, "printer-uri", self.ipp_uri),
            (TAG_NAME_WITHOUT_LANG, "job-name", job_name),
            (TAG_MIME_MEDIA_TYPE, "document-format", document_format),
        ]
        job_attrs: list[tuple[int, str, Any]] = [
            (TAG_INTEGER, "copies", copies),
            (TAG_KEYWORD, "sides", sides),
        ]
        if media:
            job_attrs.append((TAG_KEYWORD, "media", media))
        if media_col is not None:
            job_attrs.append((TAG_BEGIN_COLLECTION, "media-col", media_col))
        if print_color_mode:
            job_attrs.append((TAG_KEYWORD, "print-color-mode", print_color_mode))
        if print_quality is not None:
            job_attrs.append((TAG_ENUM, "print-quality", print_quality))
        if print_scaling:
            job_attrs.append((TAG_KEYWORD, "print-scaling", print_scaling))
        if orientation_requested is not None:
            job_attrs.append((TAG_ENUM, "orientation-requested", orientation_requested))
        return self.request(
            operation,
            operation_attributes=op_attrs,
            job_attributes=job_attrs,
            data=document,
        )

    def get_jobs(self) -> IppResponse:
        attrs: list[tuple[int, str, Any]] = [
            (TAG_CHARSET, "attributes-charset", "utf-8"),
            (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
            (TAG_URI, "printer-uri", self.ipp_uri),
            (TAG_KEYWORD, "which-jobs", "not-completed"),
            (TAG_KEYWORD, "requested-attributes", "job-id"),
            (TAG_KEYWORD, "", "job-name"),
            (TAG_KEYWORD, "", "job-state"),
            (TAG_KEYWORD, "", "job-state-reasons"),
            (TAG_KEYWORD, "", "job-originating-user-name"),
            (TAG_KEYWORD, "", "time-at-creation"),
        ]
        return self.request(OP_GET_JOBS, operation_attributes=attrs)

    def cancel_job(self, job_id: int) -> IppResponse:
        attrs: list[tuple[int, str, Any]] = [
            (TAG_CHARSET, "attributes-charset", "utf-8"),
            (TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en"),
            (TAG_URI, "printer-uri", self.ipp_uri),
            (TAG_INTEGER, "job-id", job_id),
        ]
        return self.request(OP_CANCEL_JOB, operation_attributes=attrs)
