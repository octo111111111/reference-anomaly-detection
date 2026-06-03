from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from reference_anomaly_detection.services.text_match import normalize_text, text_similarity

DEFAULT_MAILTO = "zhangyuyue@bupt.edu.cn"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"
CROSSREF_WORKS_SEARCH_URL = "https://api.crossref.org/works"


@dataclass(frozen=True)
class CrossrefWork:
    doi: str
    title: str | None
    journal: str | None
    year: int | None
    authors: list[str]


class CrossrefClient:
    """Crossref REST API 客户端，支持 SQLite 本地缓存。"""

    def __init__(
        self,
        *,
        mailto: str = DEFAULT_MAILTO,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        cache_enabled: bool = True,
        cache_path: Path | str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.mailto = mailto
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.cache_enabled = cache_enabled
        self.cache_path = Path(cache_path) if cache_path else self._default_cache_path()
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            f"ReferenceAnomalyDetection/0.3 (mailto:{mailto})",
        )
        if self.cache_enabled:
            self._init_cache()

    @staticmethod
    def _default_cache_path() -> Path:
        base = Path.home() / ".cache" / "reference-anomaly-detection"
        base.mkdir(parents=True, exist_ok=True)
        return base / "crossref_cache.sqlite"

    def _init_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crossref_cache (
                    doi TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT,
                    fetched_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crossref_search_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    fetched_at REAL NOT NULL
                )
                """
            )

    def _cache_get(self, doi: str) -> tuple[str, dict[str, Any] | None] | None:
        if not self.cache_enabled:
            return None
        with sqlite3.connect(self.cache_path) as conn:
            row = conn.execute(
                "SELECT status, payload FROM crossref_cache WHERE doi = ?",
                (doi.lower(),),
            ).fetchone()
        if row is None:
            return None
        status, payload_text = row
        payload = json.loads(payload_text) if payload_text else None
        return status, payload

    def _cache_set(
        self, doi: str, status: str, payload: dict[str, Any] | None
    ) -> None:
        if not self.cache_enabled:
            return
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO crossref_cache (doi, status, payload, fetched_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    doi.lower(),
                    status,
                    json.dumps(payload) if payload else None,
                    time.time(),
                ),
            )

    def fetch_work(self, doi: str) -> CrossrefWork | None:
        """查询 DOI；不存在返回 None，网络失败抛出 CrossrefClientError。"""
        normalized = self.normalize_doi(doi)
        cached = self._cache_get(normalized)
        if cached is not None:
            status, payload = cached
            if status == "not_found":
                return None
            if payload is not None:
                return self._parse_work(normalized, payload)

        payload, found = self._request_work(normalized)
        if not found:
            self._cache_set(normalized, "not_found", None)
            return None
        self._cache_set(normalized, "found", payload)
        return self._parse_work(normalized, payload)

    def search_works_by_bibliographic(
        self,
        *,
        title: str | None,
        year: int | None = None,
        journal: str | None = None,
        author: str | None = None,
        rows: int = 5,
    ) -> list[CrossrefWork]:
        """按书目信息检索 Crossref，返回按题名相似度排序的结果。"""
        if not title or not title.strip():
            return []

        cache_key = self._search_cache_key(title, year, journal, author, rows)
        cached = self._search_cache_get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, Any] = {
            "mailto": self.mailto,
            "rows": rows,
            "query.title": title.strip(),
        }
        if author:
            params["query.author"] = author
        if journal:
            params["query.container-title"] = journal
        filters: list[str] = []
        if year is not None:
            filters.append(f"from-pub-date:{year}")
            filters.append(f"until-pub-date:{year}")
        if filters:
            params["filter"] = ",".join(filters)

        items = self._request_search(params)
        works: list[CrossrefWork] = []
        for item in items:
            item_doi = item.get("DOI")
            if not item_doi:
                continue
            normalized = self.normalize_doi(item_doi)
            works.append(self._parse_work(normalized, item))

        works.sort(
            key=lambda w: text_similarity(title, w.title) or 0.0,
            reverse=True,
        )
        self._search_cache_set(cache_key, works)
        return works

    @staticmethod
    def _search_cache_key(
        title: str,
        year: int | None,
        journal: str | None,
        author: str | None,
        rows: int,
    ) -> str:
        raw = "|".join(
            [
                normalize_text(title),
                str(year or ""),
                normalize_text(journal),
                normalize_text(author),
                str(rows),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _search_cache_get(self, cache_key: str) -> list[CrossrefWork] | None:
        if not self.cache_enabled:
            return None
        with sqlite3.connect(self.cache_path) as conn:
            row = conn.execute(
                "SELECT payload FROM crossref_search_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return [
            CrossrefWork(
                doi=item["doi"],
                title=item.get("title"),
                journal=item.get("journal"),
                year=item.get("year"),
                authors=item.get("authors") or [],
            )
            for item in data
        ]

    def _search_cache_set(self, cache_key: str, works: list[CrossrefWork]) -> None:
        if not self.cache_enabled:
            return
        payload = [
            {
                "doi": w.doi,
                "title": w.title,
                "journal": w.journal,
                "year": w.year,
                "authors": w.authors,
            }
            for w in works
        ]
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO crossref_search_cache (cache_key, payload, fetched_at)
                VALUES (?, ?, ?)
                """,
                (cache_key, json.dumps(payload), time.time()),
            )

    def _request_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._session.get(
                    CROSSREF_WORKS_SEARCH_URL,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
                message = body.get("message") or {}
                items = message.get("items") or []
                return items if isinstance(items, list) else []
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))
        raise CrossrefClientError(
            f"Crossref 书目检索失败: {last_error}"
        ) from last_error

    def _request_work(self, doi: str) -> tuple[dict[str, Any], bool]:
        url = CROSSREF_WORKS_URL.format(doi=quote(doi, safe="/"))
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self._session.get(
                    url,
                    params={"mailto": self.mailto},
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 404:
                    return {}, False
                response.raise_for_status()
                body = response.json()
                message = body.get("message")
                if not message:
                    return {}, False
                return message, True
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))

        raise CrossrefClientError(
            f"Crossref 请求失败（DOI={doi}）: {last_error}"
        ) from last_error

    @staticmethod
    def normalize_doi(doi: str) -> str:
        value = doi.strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if value.startswith(prefix):
                value = value[len(prefix) :].strip()
        return value

    @staticmethod
    def _parse_work(doi: str, message: dict[str, Any]) -> CrossrefWork:
        titles = message.get("title") or []
        title = titles[0].strip() if titles else None

        journals = message.get("container-title") or message.get("short-container-title") or []
        journal = journals[0].strip() if journals else None

        year = _extract_year(message)
        authors = _extract_authors(message.get("author") or [])

        return CrossrefWork(
            doi=doi,
            title=title,
            journal=journal,
            year=year,
            authors=authors,
        )


class CrossrefClientError(RuntimeError):
    """Crossref API 调用失败。"""


def _extract_year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        block = message.get(key)
        if not block:
            continue
        parts = block.get("date-parts")
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _extract_authors(author_list: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for author in author_list:
        family = author.get("family", "")
        given = author.get("given", "")
        if family and given:
            names.append(f"{family} {given}".strip())
        elif family:
            names.append(family.strip())
        elif given:
            names.append(given.strip())
    return names
