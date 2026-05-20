from __future__ import annotations

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

    def check_reference(self, reference: ReferenceItem) -> RetractionCheckResult:
        doi = reference.doi
        if doi:
            doi = CrossrefClient.normalize_doi(doi)

        if not doi:
            return RetractionCheckResult(
                ref_id=reference.ref_id,
                doi=None,
                is_retracted=False,
                risk_flag=None,
            )

        original_match = self.index.lookup_by_original_doi(doi)
        if original_match is not None:
            return self._result_from_record(
                reference.ref_id,
                doi,
                original_match,
                is_retracted=True,
                risk_flag="cites_retracted_work",
            )

        notice_match = self.index.lookup_by_retraction_doi(doi)
        if notice_match is not None:
            return self._result_from_record(
                reference.ref_id,
                doi,
                notice_match,
                is_retracted=False,
                risk_flag="cites_retraction_notice",
                notice_doi=doi,
            )

        return RetractionCheckResult(
            ref_id=reference.ref_id,
            doi=doi,
            is_retracted=False,
            risk_flag=None,
        )

    @staticmethod
    def _result_from_record(
        ref_id: str,
        doi: str,
        record: RetractionRecord,
        *,
        is_retracted: bool,
        risk_flag: str,
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
        )

    def check(self, paper_input: RetractionCheckInput) -> RetractionCheckBatchResult:
        checks = [self.check_reference(ref) for ref in paper_input.references]
        return RetractionCheckBatchResult(
            paper_id=paper_input.paper_id,
            retraction_checks=checks,
        )
