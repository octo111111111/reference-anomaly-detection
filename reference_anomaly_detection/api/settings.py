from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from reference_anomaly_detection.services.retraction_watch_index import RetractionWatchIndex


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    crossref_mailto: str
    retraction_db: Path
    crossref_cache_path: Path | None
    upload_tmp_dir: Path
    cache_enabled: bool
    max_upload_bytes: int


def get_settings() -> Settings:
    upload_tmp = _env_path("UPLOAD_TMP_DIR") or Path("/tmp/reference-anomaly-api")
    retraction_db = (
        _env_path("RETRACTION_DB") or RetractionWatchIndex.default_db_path()
    )
    return Settings(
        host=os.environ.get("REFERENCE_API_HOST", "0.0.0.0"),
        port=_env_int("REFERENCE_API_PORT", 18080),
        crossref_mailto=os.environ.get(
            "CROSSREF_MAILTO",
            "zhangyuyue@bupt.edu.cn",
        ),
        retraction_db=retraction_db,
        crossref_cache_path=_env_path("CROSSREF_CACHE"),
        upload_tmp_dir=upload_tmp,
        cache_enabled=_env_bool("CROSSREF_CACHE_ENABLED", True),
        max_upload_bytes=_env_int("MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
    )
