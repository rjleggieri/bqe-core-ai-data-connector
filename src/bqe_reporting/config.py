from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries without overriding the process environment."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    mode: str = "MOCK"
    enable_live: bool = False
    client_id: str | None = None
    redirect_uri: str = "http://127.0.0.1:8765/callback"
    scopes: tuple[str, ...] = ("read:core",)
    authority: str = "https://api-identity.bqecore.com/idp"
    db_path: Path = Path("data/bqe_core_connector.sqlite3")
    utc_offset: str = "-04:00"
    log_level: str = "INFO"

    @property
    def live(self) -> bool:
        return self.mode == "LIVE" and self.enable_live

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        mode = os.getenv("BQE_MODE", "MOCK").strip().upper()
        if mode not in {"MOCK", "LIVE"}:
            raise ValueError("BQE_MODE must be MOCK or LIVE")
        scopes = tuple(os.getenv("BQE_SCOPES", "read:core").split())
        if "readwrite:core" in scopes:
            raise ValueError("readwrite:core is forbidden by this read-only connector")
        if "offline_access" in scopes:
            raise ValueError("BQE Native Apps do not support offline_access; request read:core only")
        if scopes != ("read:core",):
            raise ValueError("BQE_SCOPES must be exactly read:core")
        return cls(
            mode=mode,
            enable_live=os.getenv("BQE_ENABLE_LIVE", "NO").upper() == "YES",
            client_id=os.getenv("BQE_CLIENT_ID") or None,
            redirect_uri=os.getenv("BQE_REDIRECT_URI", cls.redirect_uri),
            scopes=scopes,
            authority=os.getenv("BQE_AUTHORITY", cls.authority).rstrip("/"),
            db_path=Path(os.getenv("BQE_DB_PATH", "data/bqe_core_connector.sqlite3")),
            utc_offset=os.getenv("BQE_UTC_OFFSET", "-04:00"),
            log_level=os.getenv("BQE_LOG_LEVEL", "INFO"),
        )

    def require_live(self) -> None:
        if not self.live:
            raise RuntimeError(
                "LIVE access is disabled. Set BQE_MODE=LIVE and BQE_ENABLE_LIVE=YES only "
                "after review and explicit approval."
            )
        if not self.client_id:
            raise RuntimeError("BQE_CLIENT_ID is required")
