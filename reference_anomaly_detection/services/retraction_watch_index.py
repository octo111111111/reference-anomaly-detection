from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from reference_anomaly_detection.services.crossref_client import CrossrefClient

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "original_doi": (
        "originalpaperdoi",
        "originaldoi",
        "original_paper_doi",
    ),
    "retraction_doi": (
        "retractiondoi",
        "retraction_paper_doi",
    ),
    "title": ("title", "articletitle"),
    "journal": ("journal", "journaltitle"),
    "publisher": ("publisher",),
    "retraction_nature": ("retractionnature", "nature", "articletype"),
    "retraction_date": ("retractiondate", "date"),
    "reason": ("reason",),
    "source_record_id": ("recordid", "id", "record_id"),
    "source_url": ("url", "urls", "link"),
}


def _normalize_column_name(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("_", "")


def _map_row_columns(fieldnames: Iterable[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    normalized = {_normalize_column_name(name): name for name in fieldnames}
    mapping: dict[str, str] = {}
    for field, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


def _cell(row: dict[str, str], column: str | None) -> str | None:
    if not column:
        return None
    value = row.get(column, "").strip()
    return value or None


def _normalize_doi_value(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return CrossrefClient.normalize_doi(value)
    except Exception:
        return None


@dataclass(frozen=True)
class RetractionRecord:
    original_doi: str | None
    retraction_doi: str | None
    title: str | None
    journal: str | None
    publisher: str | None
    retraction_nature: str | None
    retraction_date: str | None
    reason: str | None
    source_record_id: str | None
    source_url: str | None


class RetractionWatchIndexError(RuntimeError):
    """撤稿索引不可用或构建失败。"""


class RetractionWatchIndex:
    """Retraction Watch CSV 的本地 SQLite 索引。"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.is_file():
            raise RetractionWatchIndexError(
                f"撤稿索引不存在: {self.db_path}\n"
                "请先运行: reference-build-retraction-index --csv <RetractionWatch.csv>"
            )

    @staticmethod
    def default_db_path() -> Path:
        config = _load_retraction_config()
        raw = config.get("default_index_path")
        if raw:
            path = Path(str(raw))
            if path.is_absolute():
                return path
            project_root = _CONFIG_DIR.parent.parent
            return (project_root / path).resolve()
        return _CONFIG_DIR / "retraction_watch_index.sqlite"

    @classmethod
    def build_from_csv(
        cls,
        csv_path: Path | str,
        db_path: Path | str | None = None,
    ) -> Path:
        csv_path = Path(csv_path)
        if not csv_path.is_file():
            raise RetractionWatchIndexError(f"CSV 文件不存在: {csv_path}")

        target = Path(db_path) if db_path else cls.default_db_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()

        built_at = time.time()
        inserted = 0

        conn = sqlite3.connect(target)
        try:
            cls._create_schema(conn)
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                column_map = _map_row_columns(reader.fieldnames)
                for row in reader:
                    record = cls._row_to_record(row, column_map)
                    if not record.original_doi and not record.retraction_doi:
                        continue
                    cls._insert_record(conn, record, built_at)
                    inserted += 1
            conn.commit()
        finally:
            conn.close()

        if inserted == 0:
            target.unlink(missing_ok=True)
            raise RetractionWatchIndexError(
                f"未从 CSV 导入任何有效 DOI 记录: {csv_path}"
            )

        return target

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE retraction_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_doi TEXT,
                retraction_doi TEXT,
                title TEXT,
                journal TEXT,
                publisher TEXT,
                retraction_nature TEXT,
                retraction_date TEXT,
                reason TEXT,
                source_record_id TEXT,
                source_url TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_original_doi ON retraction_records(original_doi)"
        )
        conn.execute(
            "CREATE INDEX idx_retraction_doi ON retraction_records(retraction_doi)"
        )

    @classmethod
    def _row_to_record(
        cls, row: dict[str, str], column_map: dict[str, str]
    ) -> RetractionRecord:
        return RetractionRecord(
            original_doi=_normalize_doi_value(
                _cell(row, column_map.get("original_doi"))
            ),
            retraction_doi=_normalize_doi_value(
                _cell(row, column_map.get("retraction_doi"))
            ),
            title=_cell(row, column_map.get("title")),
            journal=_cell(row, column_map.get("journal")),
            publisher=_cell(row, column_map.get("publisher")),
            retraction_nature=_cell(row, column_map.get("retraction_nature")),
            retraction_date=_cell(row, column_map.get("retraction_date")),
            reason=_cell(row, column_map.get("reason")),
            source_record_id=_cell(row, column_map.get("source_record_id")),
            source_url=_cell(row, column_map.get("source_url")),
        )

    @staticmethod
    def _insert_record(
        conn: sqlite3.Connection,
        record: RetractionRecord,
        built_at: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO retraction_records (
                original_doi, retraction_doi, title, journal, publisher,
                retraction_nature, retraction_date, reason,
                source_record_id, source_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.original_doi,
                record.retraction_doi,
                record.title,
                record.journal,
                record.publisher,
                record.retraction_nature,
                record.retraction_date,
                record.reason,
                record.source_record_id,
                record.source_url,
                built_at,
            ),
        )

    def lookup_by_original_doi(self, doi: str) -> RetractionRecord | None:
        normalized = _normalize_doi_value(doi)
        if not normalized:
            return None
        return self._fetch_one(
            "SELECT * FROM retraction_records WHERE original_doi = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (normalized,),
        )

    def lookup_by_retraction_doi(self, doi: str) -> RetractionRecord | None:
        normalized = _normalize_doi_value(doi)
        if not normalized:
            return None
        return self._fetch_one(
            "SELECT * FROM retraction_records WHERE retraction_doi = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (normalized,),
        )

    def _fetch_one(self, query: str, params: tuple[str, ...]) -> RetractionRecord | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return RetractionRecord(
            original_doi=row["original_doi"],
            retraction_doi=row["retraction_doi"],
            title=row["title"],
            journal=row["journal"],
            publisher=row["publisher"],
            retraction_nature=row["retraction_nature"],
            retraction_date=row["retraction_date"],
            reason=row["reason"],
            source_record_id=row["source_record_id"],
            source_url=row["source_url"],
        )


def _load_retraction_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "retraction.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}
