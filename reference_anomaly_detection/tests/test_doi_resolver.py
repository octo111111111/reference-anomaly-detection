from __future__ import annotations

from unittest.mock import MagicMock

from reference_anomaly_detection.models.schemas import ReferenceItem
from reference_anomaly_detection.services.crossref_client import CrossrefWork
from reference_anomaly_detection.services.doi_resolver import DoiResolver


class TestDoiResolver:
    def test_resolve_reference_success(self) -> None:
        client = MagicMock()
        client.search_works_by_bibliographic.return_value = [
            CrossrefWork(
                doi="10.1000/resolved.1",
                title="Example title for matching",
                journal="Journal A",
                year=2020,
                authors=["Smith J"],
            )
        ]
        resolver = DoiResolver(crossref_client=client)
        ref = ReferenceItem(
            ref_id="R001",
            raw_text="ref",
            title="Example title for matching",
            journal="Journal A",
            year=2020,
        )
        result = resolver.resolve_reference(ref)
        assert result.crossref_search_status == "resolved"
        assert result.resolved_doi == "10.1000/resolved.1"
        assert result.resolve_score is not None
        assert result.resolve_score >= 0.85
        assert result.resolve_source == "crossref_search"

    def test_skips_when_doi_present(self) -> None:
        client = MagicMock()
        resolver = DoiResolver(crossref_client=client)
        ref = ReferenceItem(
            ref_id="R001",
            raw_text="ref",
            title="Title",
            doi="10.1000/existing",
        )
        result = resolver.resolve_reference(ref)
        assert result.crossref_search_status == "not_needed"
        assert result.resolved_doi is None
        client.search_works_by_bibliographic.assert_not_called()

    def test_low_score_not_resolved(self) -> None:
        client = MagicMock()
        client.search_works_by_bibliographic.return_value = [
            CrossrefWork(
                doi="10.1000/other",
                title="Completely unrelated article",
                journal="Other",
                year=1999,
                authors=[],
            )
        ]
        resolver = DoiResolver(crossref_client=client)
        ref = ReferenceItem(
            ref_id="R001",
            raw_text="ref",
            title="Example title for matching",
            journal="Journal A",
            year=2020,
        )
        result = resolver.resolve_reference(ref)
        assert result.crossref_search_status == "low_score"
        assert result.resolved_doi is None
