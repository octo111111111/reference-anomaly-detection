from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reference_anomaly_detection.models.schemas import DoiResolveResult, ReferenceItem
from reference_anomaly_detection.services.crossref_client import (
    CrossrefClient,
    CrossrefClientError,
    CrossrefWork,
)
from reference_anomaly_detection.services.journal_match import JournalMatcher
from reference_anomaly_detection.services.text_match import text_similarity

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_thresholds() -> dict[str, Any]:
    path = _CONFIG_DIR / "thresholds.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


class DoiResolver:
    """为无 DOI 的参考文献通过 Crossref 书目检索解析 DOI。"""

    def __init__(
        self,
        crossref_client: CrossrefClient | None = None,
        *,
        thresholds_path: Path | None = None,
    ) -> None:
        self.crossref = crossref_client or CrossrefClient()
        thresholds = _load_thresholds()
        if thresholds_path and thresholds_path.exists():
            with thresholds_path.open(encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
            if isinstance(loaded, dict):
                thresholds = loaded
        self.resolve_threshold = float(thresholds.get("doi_resolve_threshold", 0.85))
        self.max_candidates = int(thresholds.get("doi_resolve_max_candidates", 5))
        self._journal_matcher = JournalMatcher()

    def resolve_reference(self, reference: ReferenceItem) -> DoiResolveResult:
        if reference.doi or not reference.title:
            return DoiResolveResult(ref_id=reference.ref_id)

        author = reference.authors[0] if reference.authors else None
        try:
            candidates = self.crossref.search_works_by_bibliographic(
                title=reference.title,
                year=reference.year,
                journal=reference.journal,
                author=author,
                rows=self.max_candidates,
            )
        except CrossrefClientError:
            return DoiResolveResult(ref_id=reference.ref_id)

        best_doi, best_score = self._pick_best(reference, candidates)
        if best_doi is None or best_score is None:
            return DoiResolveResult(ref_id=reference.ref_id)
        if best_score < self.resolve_threshold:
            return DoiResolveResult(
                ref_id=reference.ref_id,
                resolve_score=best_score,
                resolve_source="crossref_search",
            )
        return DoiResolveResult(
            ref_id=reference.ref_id,
            resolved_doi=best_doi,
            resolve_score=best_score,
            resolve_source="crossref_search",
        )

    def _pick_best(
        self, reference: ReferenceItem, candidates: list[CrossrefWork]
    ) -> tuple[str | None, float | None]:
        best_doi: str | None = None
        best_score = 0.0
        for work in candidates:
            title_score = text_similarity(reference.title, work.title) or 0.0
            journal_score = (
                self._journal_matcher.similarity(reference.journal, work.journal)
                or 0.0
            )
            year_ok = True
            if reference.year is not None and work.year is not None:
                year_ok = abs(reference.year - work.year) <= 1
            parts = [title_score]
            if reference.journal and work.journal:
                parts.append(journal_score)
            if reference.year is not None and work.year is not None:
                parts.append(1.0 if year_ok else 0.0)
            score = sum(parts) / len(parts)
            if score > best_score:
                best_score = score
                best_doi = work.doi
        if best_doi is None:
            return None, None
        return best_doi, round(best_score, 4)

    def resolve_batch(
        self, references: list[ReferenceItem]
    ) -> tuple[list[DoiResolveResult], dict[str, str]]:
        results = [self.resolve_reference(ref) for ref in references]
        resolved_map = {
            r.ref_id: r.resolved_doi
            for r in results
            if r.resolved_doi
        }
        return results, resolved_map
