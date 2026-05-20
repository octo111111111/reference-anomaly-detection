from __future__ import annotations

from reference_anomaly_detection.models.schemas import (
    DoiCheckResult,
    ReferenceItem,
    RetractionCheckResult,
    RiskSummaryInput,
)
from reference_anomaly_detection.reports.report_builder import RiskReportBuilder


class TestRiskReportBuilder:
    def test_no_issues_empty_risk_items(self) -> None:
        report = RiskReportBuilder().build(
            RiskSummaryInput(
                paper_id="paper_test",
                references=[
                    ReferenceItem(ref_id="R001", raw_text="ok", doi="10.1/ok"),
                ],
                doi_checks=[
                    DoiCheckResult(ref_id="R001", doi="10.1/ok", doi_exists=True),
                ],
                retraction_checks=[
                    RetractionCheckResult(ref_id="R001", doi="10.1/ok"),
                ],
            ),
        )
        assert report.paper_id == "paper_test"
        assert report.module == "reference_anomaly_detection"
        assert report.risk_items == []
        assert report.summary.total_references == 1
        assert report.summary.doi_found_count == 1
        assert report.summary.doi_issue_count == 0

    def test_doi_and_retraction_risk_items(self) -> None:
        report = RiskReportBuilder().build(
            RiskSummaryInput(
                paper_id="paper_test",
                references=[
                    ReferenceItem(ref_id="R001", raw_text="a", doi="10.1/a"),
                    ReferenceItem(ref_id="R002", raw_text="b", doi="10.1/b"),
                ],
                doi_checks=[
                    DoiCheckResult(
                        ref_id="R001",
                        doi="10.1/a",
                        doi_exists=False,
                        risk_flag="doi_not_found",
                    ),
                    DoiCheckResult(
                        ref_id="R002",
                        doi="10.1/b",
                        doi_exists=True,
                        risk_flag="title_mismatch",
                    ),
                ],
                retraction_checks=[
                    RetractionCheckResult(
                        ref_id="R001",
                        doi="10.1/a",
                        is_retracted=True,
                        risk_flag="cites_retracted_work",
                    ),
                    RetractionCheckResult(ref_id="R002", doi="10.1/b"),
                ],
            ),
        )
        assert report.summary.total_references == 2
        assert report.summary.doi_not_found_count == 1
        assert report.summary.doi_mismatch_count == 1
        assert report.summary.doi_issue_count == 2
        assert report.summary.retracted_reference_count == 1
        assert len(report.risk_items) >= 1
        overview = report.risk_items[0]
        assert overview.risk_type == "reference_anomaly"
        assert overview.severity == "high"
        assert overview.review_required is True

    def test_retraction_skipped_stats(self) -> None:
        report = RiskReportBuilder().build(
            RiskSummaryInput(
                paper_id="paper_test",
                references=[ReferenceItem(ref_id="R001", raw_text="x")],
                doi_checks=[
                    DoiCheckResult(ref_id="R001", risk_flag="missing_doi"),
                ],
                retraction_checks=[],
                retraction_check_skipped=True,
                retraction_skip_reason="索引不存在",
            ),
        )
        assert report.retraction_check_skipped is True
        assert report.retraction_skip_reason == "索引不存在"
        assert report.summary.retracted_reference_count == 0
