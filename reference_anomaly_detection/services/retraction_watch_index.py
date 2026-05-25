from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from reference_anomaly_detection.services.crossref_client import CrossrefClient
from reference_anomaly_detection.services.journal_match import JournalMatcher
from reference_anomaly_detection.services.text_match import (
    fts_query_from_title,
    normalize_text,
    text_similarity,
)

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


def _load_retraction_config() -> dict[str, Any]:
    path = _CONFIG_DIR / "retraction.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


def _load_thresholds() -> dict[str, Any]:
    path = _CONFIG_DIR / "thresholds.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class RetractionRecord:
    record_id: int | None = None
    original_doi: str | None = None
    retraction_doi: str | None = None
    title: str | None = None
    journal: str | None = None
    publisher: str | None = None
    retraction_nature: str | None = None
    retraction_date: str | None = None
    reason: str | None = None
    source_record_id: str | None = None
    source_url: str | None = None


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
        config = _load_retraction_config()
        thresholds = _load_thresholds()
        self._fts_top_k = int(config.get("fts_top_k", 20))
        self._title_match_threshold = float(
            config.get("retraction_title_match_threshold", 0.92)
        )
        self._title_review_threshold = float(
            config.get("retraction_title_review_threshold", 0.85)
        )
        self._journal_threshold = float(
            thresholds.get("doi_journal_match_threshold", 0.75)
        )
        self._year_tolerance = int(thresholds.get("doi_year_tolerance", 1))
        self._journal_matcher = JournalMatcher()

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
                    record_id = cls._insert_record(conn, record, built_at)
                    if record.title:
                        title_norm = normalize_text(record.title)
                        if title_norm:
                            conn.execute(
                                """
                                INSERT INTO retraction_title_fts (rowid, title_normalized)
                                VALUES (?, ?)
                                """,
                                (record_id, title_norm),
                            )
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
                title_normalized TEXT,
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
        conn.execute(
            """
            CREATE VIRTUAL TABLE retraction_title_fts USING fts5(
                title_normalized,
                tokenize='unicode61'
            )
            """
        )

    @classmethod
    def _row_to_record(
        cls, row: dict[str, str], column_map: dict[str, str]
    ) -> RetractionRecord:
        title = _cell(row, column_map.get("title"))
        return RetractionRecord(
            original_doi=_normalize_doi_value(
                _cell(row, column_map.get("original_doi"))
            ),
            retraction_doi=_normalize_doi_value(
                _cell(row, column_map.get("retraction_doi"))
            ),
            title=title,
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
    ) -> int:
        title_norm = normalize_text(record.title) if record.title else None
        cursor = conn.execute(
            """
            INSERT INTO retraction_records (
                original_doi, retraction_doi, title, title_normalized, journal,
                publisher, retraction_nature, retraction_date, reason,
                source_record_id, source_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.original_doi,
                record.retraction_doi,
                record.title,
                title_norm,
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
        return int(cursor.lastrowid)

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

    def lookup_by_title(
        self,
        title: str | None,
        *,
        year: int | None = None,
        journal: str | None = None,
        top_k: int | None = None,
    ) -> list[tuple[RetractionRecord, float]]:
        if not title or not normalize_text(title):
            return []

        limit = top_k or self._fts_top_k
        candidates = self._fts_candidates(title, limit=limit)
        if not candidates:
            candidates = self._fallback_title_scan(title, limit=limit)

        scored: list[tuple[RetractionRecord, float]] = []
        for record in candidates:
            if not record.title:
                continue
            score = text_similarity(title, record.title)
            if score is None:
                continue
            if journal and record.journal:
                j_score = self._journal_matcher.similarity(journal, record.journal)
                if j_score is not None and j_score < self._journal_threshold:
                    continue
            scored.append((record, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    def best_title_match(
        self,
        title: str | None,
        *,
        year: int | None = None,
        journal: str | None = None,
    ) -> tuple[RetractionRecord, float] | None:
        matches = self.lookup_by_title(title, year=year, journal=journal)
        if not matches:
            return None
        record, score = matches[0]
        if score < self._title_review_threshold:
            return None
        return record, score

    @property
    def title_match_threshold(self) -> float:
        return self._title_match_threshold

    @property
    def title_review_threshold(self) -> float:
        return self._title_review_threshold

    def _fts_candidates(self, title: str, *, limit: int) -> list[RetractionRecord]:
        query = fts_query_from_title(title)
        if not query:
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT r.*
                    FROM retraction_title_fts AS fts
                    JOIN retraction_records AS r ON r.id = fts.rowid
                    WHERE retraction_title_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._row_to_record_obj(row) for row in rows]

    def _fallback_title_scan(self, title: str, *, limit: int) -> list[RetractionRecord]:
        prefix = normalize_text(title)[:40]
        if not prefix:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM retraction_records
                WHERE title_normalized IS NOT NULL
                  AND title_normalized LIKE ?
                LIMIT ?
                """,
                (f"%{prefix[:24]}%", limit * 3),
            ).fetchall()
        return [self._row_to_record_obj(row) for row in rows]

    def _fetch_one(self, query: str, params: tuple[str, ...]) -> RetractionRecord | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return self._row_to_record_obj(row)

    @staticmethod
    def _row_to_record_obj(row: sqlite3.Row) -> RetractionRecord:
        keys = row.keys()
        record_id = row["id"] if "id" in keys else None
        return RetractionRecord(
            record_id=int(record_id) if record_id is not None else None,
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
