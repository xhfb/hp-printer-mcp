from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Load project .env into os.environ (does not override existing vars)."""
    candidates: list[Path] = []
    env_file = os.getenv("HP_PRINTER_ENV_FILE", "").strip()
    if env_file:
        candidates.append(Path(env_file))
    candidates.extend(
        [
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ]
    )
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        break
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_paths(name: str) -> list[Path]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    return [Path(p.strip()).resolve() for p in raw.split(os.pathsep) if p.strip()]


@dataclass(frozen=True)
class Settings:
    printer_host: str
    printer_name: str | None
    scan_output_dir: Path
    use_https: bool
    snmp_community: str
    allowed_paths: list[Path]
    escl_timeout_sec: float
    scan_poll_interval_sec: float
    scan_poll_max_sec: float

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        host = self.printer_host.rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"{scheme}://{host}"

    @property
    def escl_base(self) -> str:
        return f"{self.base_url}/eSCL"

    def ensure_allowed_path(self, path: str | Path, *, for_write: bool = False) -> Path:
        resolved = Path(path).expanduser().resolve()
        allowed = list(self.allowed_paths)
        if for_write and self.scan_output_dir not in allowed:
            allowed.append(self.scan_output_dir.resolve())

        if not allowed:
            return resolved

        for base in allowed:
            try:
                resolved.relative_to(base)
                return resolved
            except ValueError:
                continue
        bases = ", ".join(str(p) for p in allowed)
        raise PermissionError(
            f"Path '{resolved}' is outside allowed directories: {bases}"
        )


def load_settings() -> Settings:
    _load_dotenv()
    host = os.getenv("HP_PRINTER_HOST", "").strip()
    scan_dir_raw = os.getenv("HP_SCAN_OUTPUT_DIR", "").strip()
    if scan_dir_raw:
        scan_output_dir = Path(scan_dir_raw).expanduser()
    else:
        scan_output_dir = Path.cwd() / "output"

    default_allowed: list[Path] = []
    docs = Path.home() / "Documents"
    if docs.exists():
        default_allowed.append(docs.resolve())
    default_allowed.append(scan_output_dir.resolve())

    extra_allowed = _env_paths("HP_ALLOWED_PATHS")
    allowed_paths = extra_allowed or default_allowed

    return Settings(
        printer_host=host,
        printer_name=os.getenv("HP_PRINTER_NAME", "").strip() or None,
        scan_output_dir=scan_output_dir,
        use_https=_env_bool("HP_USE_HTTPS", False),
        snmp_community=os.getenv("HP_SNMP_COMMUNITY", "public").strip() or "public",
        allowed_paths=allowed_paths,
        escl_timeout_sec=float(os.getenv("HP_ESCL_TIMEOUT_SEC", "30")),
        scan_poll_interval_sec=float(os.getenv("HP_SCAN_POLL_INTERVAL_SEC", "1")),
        scan_poll_max_sec=float(os.getenv("HP_SCAN_POLL_MAX_SEC", "120")),
    )


def ok(data: Any = None) -> dict[str, Any]:
    return {"success": True, "error": None, "data": data}


def fail(message: str, *, data: Any = None) -> dict[str, Any]:
    return {"success": False, "error": message, "data": data}
