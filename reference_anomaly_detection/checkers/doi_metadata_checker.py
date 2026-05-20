from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from reference_anomaly_detection.models.schemas import (
    DoiCheckInput,
    DoiCheckResult,
    DoiCheckBatchResult,
    ReferenceItem,
)
from reference_anomaly_detection.services.crossref_client import (
    CrossrefClient,
    CrossrefClientError,
    CrossrefWork,
)

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str | None, b: str | None) -> float | None:
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na or not nb:
        return None
    return fuzz.token_set_ratio(na, nb) / 100.0


class DoiMetadataChecker:
    """模块三：DOI 存在性与 Crossref 元数据一致性校验。"""

    def __init__(
        self,
        crossref_client: CrossrefClient | None = None,
        *,
        thresholds_path: Path | None = None,
        journal_aliases_path: Path | None = None,
    ) -> None:
        self.crossref = crossref_client or CrossrefClient()
        thresholds = _load_yaml(thresholds_path or _CONFIG_DIR / "thresholds.yaml")
        aliases = _load_yaml(journal_aliases_path or _CONFIG_DIR / "journal_aliases.yaml")

        self.title_high_threshold = float(
            thresholds.get("doi_title_match_high_risk_threshold", 0.6)
        )
        self.title_medium_threshold = float(
            thresholds.get("doi_title_match_medium_risk_threshold", 0.8)
        )
        self.journal_threshold = float(
            thresholds.get("doi_journal_match_threshold", 0.75)
        )
        self.year_tolerance = int(thresholds.get("doi_year_tolerance", 1))
        self._journal_aliases = self._build_alias_index(aliases)

    @staticmethod
    def _build_alias_index(aliases: dict[str, Any]) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for canonical, variants in aliases.items():
            names = {_normalize_text(canonical)}
            if isinstance(variants, list):
                names.update(_normalize_text(v) for v in variants if v)
            index[_normalize_text(canonical)] = names
            for variant in variants if isinstance(variants, list) else []:
                key = _normalize_text(variant)
                index.setdefault(key, set()).update(names)
        return index

    def _journal_candidates(self, name: str | None) -> set[str]:
        normalized = _normalize_text(name)
        if not normalized:
            return set()
        candidates = {normalized}
        if normalized in self._journal_aliases:
            candidates.update(self._journal_aliases[normalized])
        for key, group in self._journal_aliases.items():
            if normalized in group or key == normalized:
                candidates.update(group)
                candidates.add(key)
        return candidates

    def _journal_similarity(
        self, ref_journal: str | None, crossref_journal: str | None
    ) -> float | None:
        if not ref_journal or not crossref_journal:
            return None
        ref_candidates = self._journal_candidates(ref_journal)
        crossref_candidates = self._journal_candidates(crossref_journal)
        best = 0.0
        for left in ref_candidates:
            for right in crossref_candidates:
                score = fuzz.token_set_ratio(left, right) / 100.0
                best = max(best, score)
        direct = _similarity(ref_journal, crossref_journal)
        if direct is not None:
            best = max(best, direct)
        return best

    def _year_matches(self, ref_year: int | None, crossref_year: int | None) -> bool | None:
        if ref_year is None or crossref_year is None:
            return None
        return abs(ref_year - crossref_year) <= self.year_tolerance

    def _year_score(self, ref_year: int | None, crossref_year: int | None) -> float | None:
        if ref_year is None or crossref_year is None:
            return None
        diff = abs(ref_year - crossref_year)
        if diff == 0:
            return 1.0
        if diff <= self.year_tolerance:
            return 0.5
        return 0.0

    def _metadata_match_score(
        self,
        title_score: float | None,
        year_score: float | None,
        journal_score: float | None,
    ) -> float | None:
        parts = [s for s in (title_score, year_score, journal_score) if s is not None]
        if not parts:
            return None
        return round(sum(parts) / len(parts), 4)

    def _resolve_risk_flag(
        self,
        *,
        doi: str | None,
        doi_exists: bool | None,
        title_score: float | None,
        year_matches: bool | None,
        journal_score: float | None,
        ref_title: str | None,
        ref_journal: str | None,
        api_error: bool,
    ) -> str | None:
        if api_error:
            return "api_error"
        if not doi:
            return "missing_doi"
        if doi_exists is False:
            return "doi_not_found"
        if ref_title and title_score is not None and title_score < self.title_high_threshold:
            return "title_mismatch"
        if year_matches is False:
            return "year_mismatch"
        if (
            ref_journal
            and journal_score is not None
            and journal_score < self.journal_threshold
        ):
            return "journal_mismatch"
        if ref_title and title_score is not None and title_score < self.title_medium_threshold:
            return "title_possible_mismatch"
        return None

    def check_reference(self, reference: ReferenceItem) -> DoiCheckResult:
        doi = reference.doi
        if doi:
            doi = self.crossref.normalize_doi(doi)

        if not doi:
            return DoiCheckResult(
                ref_id=reference.ref_id,
                doi=None,
                doi_exists=None,
                metadata_match_score=None,
                matched_title=None,
                matched_year=None,
                matched_journal=None,
                crossref_title=None,
                crossref_journal=None,
                risk_flag="missing_doi",
            )

        api_error = False
        work: CrossrefWork | None = None
        try:
            work = self.crossref.fetch_work(doi)
        except CrossrefClientError:
            api_error = True

        if api_error:
            return DoiCheckResult(
                ref_id=reference.ref_id,
                doi=doi,
                doi_exists=None,
                metadata_match_score=None,
                matched_title=None,
                matched_year=None,
                matched_journal=None,
                crossref_title=None,
                crossref_journal=None,
                risk_flag="api_error",
            )

        if work is None:
            return DoiCheckResult(
                ref_id=reference.ref_id,
                doi=doi,
                doi_exists=False,
                metadata_match_score=0.0,
                matched_title=False,
                matched_year=False,
                matched_journal=False,
                crossref_title=None,
                crossref_journal=None,
                risk_flag="doi_not_found",
            )

        title_score = _similarity(reference.title, work.title)
        journal_score = self._journal_similarity(reference.journal, work.journal)
        year_matches = self._year_matches(reference.year, work.year)
        year_score = self._year_score(reference.year, work.year)

        matched_title = (
            title_score is not None and title_score >= self.title_medium_threshold
        )
        matched_journal = (
            journal_score is not None and journal_score >= self.journal_threshold
        )
        matched_year = year_matches if year_matches is not None else None

        metadata_match_score = self._metadata_match_score(
            title_score, year_score, journal_score
        )

        risk_flag = self._resolve_risk_flag(
            doi=doi,
            doi_exists=True,
            title_score=title_score,
            year_matches=year_matches,
            journal_score=journal_score,
            ref_title=reference.title,
            ref_journal=reference.journal,
            api_error=False,
        )

        return DoiCheckResult(
            ref_id=reference.ref_id,
            doi=doi,
            doi_exists=True,
            metadata_match_score=metadata_match_score,
            matched_title=matched_title if reference.title else None,
            matched_year=matched_year,
            matched_journal=matched_journal if reference.journal else None,
            crossref_title=work.title,
            crossref_journal=work.journal,
            risk_flag=risk_flag,
        )

    def check(self, paper_input: DoiCheckInput) -> DoiCheckBatchResult:
        checks = [self.check_reference(ref) for ref in paper_input.references]
        return DoiCheckBatchResult(
            paper_id=paper_input.paper_id,
            doi_checks=checks,
        )
