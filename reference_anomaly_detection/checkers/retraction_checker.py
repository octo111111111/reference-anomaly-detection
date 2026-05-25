from __future__ import annotations

import re

from reference_anomaly_detection.models.schemas import (
    ReferenceItem,
    RetractionCheckBatchResult,
    RetractionCheckInput,
    RetractionCheckResult,
)
from reference_anomaly_detection.services.crossref_client import CrossrefClient
from reference_anomaly_detection.services.retraction_watch_index import (
    RetractionRecord,
    RetractionWatchIndex,
)


class RetractionChecker:
    """模块四：基于本地 Retraction Watch 索引检测撤稿引用。"""

    def __init__(self, index: RetractionWatchIndex) -> None:
        self.index = index

    def check_reference(
        self,
        reference: ReferenceItem,
        *,
        resolved_doi: str | None = None,
    ) -> RetractionCheckResult:
        if reference.doi:
            doi = CrossrefClient.normalize_doi(reference.doi)
            return self._check_by_doi(reference.ref_id, doi)

        if resolved_doi:
            normalized = CrossrefClient.normalize_doi(resolved_doi)
            result = self._check_by_doi(reference.ref_id, normalized)
            if result.risk_flag is not None:
                return RetractionCheckResult(
                    ref_id=result.ref_id,
                    doi=normalized,
                    is_retracted=result.is_retracted,
                    notice_doi=result.notice_doi,
                    retraction_nature=result.retraction_nature,
                    retraction_date=result.retraction_date,
                    reason=result.reason,
                    risk_flag=result.risk_flag,
                    match_method="doi",
                    title_match_score=None,
                    matched_title=None,
                )

        title = reference.title or _title_from_raw_text(reference)
        if title:
            return self._check_by_title(reference.ref_id, title, reference)

        return RetractionCheckResult(
            ref_id=reference.ref_id,
            doi=None,
            is_retracted=False,
            risk_flag=None,
        )

    def _check_by_doi(self, ref_id: str, doi: str) -> RetractionCheckResult:
        original_match = self.index.lookup_by_original_doi(doi)
        if original_match is not None:
            return self._result_from_record(
                ref_id,
                doi,
                original_match,
                is_retracted=True,
                risk_flag="cites_retracted_work",
                match_method="doi",
            )

        notice_match = self.index.lookup_by_retraction_doi(doi)
        if notice_match is not None:
            return self._result_from_record(
                ref_id,
                doi,
                notice_match,
                is_retracted=False,
                risk_flag="cites_retraction_notice",
                match_method="doi",
                notice_doi=doi,
            )

        return RetractionCheckResult(
            ref_id=ref_id,
            doi=doi,
            is_retracted=False,
            risk_flag=None,
        )

    def _check_by_title(
        self,
        ref_id: str,
        title: str,
        reference: ReferenceItem,
    ) -> RetractionCheckResult:
        match = self.index.best_title_match(
            title,
            year=reference.year,
            journal=reference.journal,
        )
        if match is None:
            return RetractionCheckResult(
                ref_id=ref_id,
                doi=None,
                is_retracted=False,
                risk_flag=None,
            )

        record, score = match
        if score >= self.index.title_match_threshold:
            risk_flag = "cites_retracted_work"
        else:
            risk_flag = "cites_retracted_work_title_possible"

        return self._result_from_record(
            ref_id,
            record.original_doi,
            record,
            is_retracted=True,
            risk_flag=risk_flag,
            match_method="title",
            title_match_score=score,
            matched_title=record.title,
        )

    @staticmethod
    def _result_from_record(
        ref_id: str,
        doi: str | None,
        record: RetractionRecord,
        *,
        is_retracted: bool,
        risk_flag: str,
        match_method: str | None = None,
        title_match_score: float | None = None,
        matched_title: str | None = None,
        notice_doi: str | None = None,
    ) -> RetractionCheckResult:
        return RetractionCheckResult(
            ref_id=ref_id,
            doi=doi,
            is_retracted=is_retracted,
            notice_doi=notice_doi or record.retraction_doi,
            retraction_nature=record.retraction_nature,
            retraction_date=record.retraction_date,
            reason=record.reason,
            risk_flag=risk_flag,
            match_method=match_method,
            title_match_score=title_match_score,
            matched_title=matched_title,
        )

    def check(
        self,
        paper_input: RetractionCheckInput,
        *,
        resolved_dois: dict[str, str] | None = None,
    ) -> RetractionCheckBatchResult:
        resolved = resolved_dois or {}
        checks = [
            self.check_reference(
                ref,
                resolved_doi=resolved.get(ref.ref_id),
            )
            for ref in paper_input.references
        ]
        return RetractionCheckBatchResult(
            paper_id=paper_input.paper_id,
            retraction_checks=checks,
        )


def _title_from_raw_text(reference: ReferenceItem) -> str | None:
    """从 raw_text 粗略提取题名（无结构化 title 时的回退）。"""
    text = reference.raw_text
    for marker in reference.citation_markers:
        text = re.sub(rf"^\[?{re.escape(marker.strip('[]'))}\]?\s*", "", text)
    text = re.sub(
        r"doi:\s*10\.\d{4,9}/[-._;()/:A-Za-z0-9]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"https?://(?:dx\.)?doi\.org/\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(19|20)\d{2}\b[;:\d()\s\-–,]*.*$", "", text)
    segments = [p.strip() for p in re.split(r"\.\s+", text) if p.strip()]
    if len(segments) >= 2:
        return segments[-2] if segments[-1].lower() in {
            "pp",
            "vol",
        } else segments[1]
    if segments:
        return segments[0]
    return None
