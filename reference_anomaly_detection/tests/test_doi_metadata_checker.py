from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reference_anomaly_detection.checkers.doi_metadata_checker import DoiMetadataChecker
from reference_anomaly_detection.models.schemas import DoiCheckInput, ReferenceItem
from reference_anomaly_detection.services.crossref_client import CrossrefWork


def _mock_client(work_by_doi: dict[str, CrossrefWork | None]) -> MagicMock:
    client = MagicMock()
    client.normalize_doi.side_effect = lambda d: d.strip().lower().replace("doi:", "")
    client.fetch_work.side_effect = lambda doi: work_by_doi.get(doi)
    return client


class TestDoiMetadataChecker:
    def setup_method(self) -> None:
        self.checker = DoiMetadataChecker(crossref_client=_mock_client({}))

    def test_missing_doi(self) -> None:
        result = self.checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="No DOI reference",
                title="Some title",
                year=2020,
            )
        )
        assert result.risk_flag == "missing_doi"
        assert result.doi_exists is None

    def test_doi_not_found(self) -> None:
        client = _mock_client({"10.1000/notfound": None})
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="Bad DOI",
                title="Example",
                doi="10.1000/notfound",
            )
        )
        assert result.doi_exists is False
        assert result.risk_flag == "doi_not_found"

    def test_full_match(self) -> None:
        client = _mock_client(
            {
                "10.1000/match": CrossrefWork(
                    doi="10.1000/match",
                    title="Example title",
                    journal="Journal A",
                    year=2020,
                    authors=["Smith J"],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="[1] Smith J. Example title. Journal A. 2020.",
                title="Example title",
                authors=["Smith J"],
                journal="Journal A",
                year=2020,
                doi="10.1000/match",
            )
        )
        assert result.doi_exists is True
        assert result.matched_title is True
        assert result.matched_year is True
        assert result.matched_journal is True
        assert result.risk_flag is None
        assert result.metadata_match_score is not None
        assert result.metadata_match_score >= 0.8

    def test_title_mismatch(self) -> None:
        client = _mock_client(
            {
                "10.1000/wrong": CrossrefWork(
                    doi="10.1000/wrong",
                    title="Completely different article",
                    journal="Journal A",
                    year=2020,
                    authors=[],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="ref",
                title="Example title",
                journal="Journal A",
                year=2020,
                doi="10.1000/wrong",
            )
        )
        assert result.risk_flag == "title_mismatch"
        assert result.matched_title is False

    def test_journal_mismatch(self) -> None:
        client = _mock_client(
            {
                "10.1000/journal": CrossrefWork(
                    doi="10.1000/journal",
                    title="Example title",
                    journal="Physical Review Letters",
                    year=2020,
                    authors=[],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="ref",
                title="Example title",
                journal="Nature Medicine",
                year=2020,
                doi="10.1000/journal",
            )
        )
        assert result.risk_flag == "journal_mismatch"
        assert result.matched_journal is False
        assert result.crossref_journal == "Physical Review Letters"

    def test_year_mismatch(self) -> None:
        client = _mock_client(
            {
                "10.1000/year": CrossrefWork(
                    doi="10.1000/year",
                    title="Example title",
                    journal="Journal A",
                    year=2015,
                    authors=[],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="ref",
                title="Example title",
                journal="Journal A",
                year=2020,
                doi="10.1000/year",
            )
        )
        assert result.risk_flag == "year_mismatch"
        assert result.matched_year is False

    def test_journal_alias_match(self) -> None:
        client = _mock_client(
            {
                "10.1000/alias": CrossrefWork(
                    doi="10.1000/alias",
                    title="Protein study",
                    journal="Journal of Biological Chemistry",
                    year=2019,
                    authors=[],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="ref",
                title="Protein study",
                journal="J Biol Chem",
                year=2019,
                doi="10.1000/alias",
            )
        )
        assert result.matched_journal is True
        assert result.risk_flag is None

    def test_batch_check(self) -> None:
        client = _mock_client(
            {
                "10.1000/a": CrossrefWork(
                    doi="10.1000/a",
                    title="Title A",
                    journal="Journal A",
                    year=2020,
                    authors=[],
                )
            }
        )
        checker = DoiMetadataChecker(crossref_client=client)
        batch = checker.check(
            DoiCheckInput(
                paper_id="batch_test",
                references=[
                    ReferenceItem(
                        ref_id="R001",
                        raw_text="a",
                        title="Title A",
                        journal="Journal A",
                        year=2020,
                        doi="10.1000/a",
                    ),
                    ReferenceItem(
                        ref_id="R002",
                        raw_text="b",
                        title="Title B",
                    ),
                ],
            )
        )
        assert batch.paper_id == "batch_test"
        assert len(batch.doi_checks) == 2
        assert batch.doi_checks[0].risk_flag is None
        assert batch.doi_checks[1].risk_flag == "missing_doi"

    def test_extract_json_roundtrip(self, tmp_path: Path) -> None:
        extract_payload = {
            "paper_id": "roundtrip",
            "references": [
                {
                    "ref_id": "R001",
                    "raw_text": "[1] Smith J. Example title. Journal A. 2020.",
                    "title": "Example title",
                    "authors": ["Smith J"],
                    "journal": "Journal A",
                    "year": 2020,
                    "doi": "10.1000/roundtrip",
                }
            ],
        }
        extract_file = tmp_path / "extract.json"
        extract_file.write_text(json.dumps(extract_payload), encoding="utf-8")

        client = _mock_client(
            {
                "10.1000/roundtrip": CrossrefWork(
                    doi="10.1000/roundtrip",
                    title="Example title",
                    journal="Journal A",
                    year=2020,
                    authors=["Smith J"],
                )
            }
        )
        payload = json.loads(extract_file.read_text(encoding="utf-8"))
        refs = [ReferenceItem.model_validate(r) for r in payload["references"]]
        batch = DoiMetadataChecker(crossref_client=client).check(
            DoiCheckInput(paper_id=payload["paper_id"], references=refs),
        )
        assert batch.doi_checks[0].doi_exists is True


class TestCrossrefClientNormalize:
    def test_normalize_doi(self) -> None:
        from reference_anomaly_detection.services.crossref_client import CrossrefClient

        assert (
            CrossrefClient.normalize_doi("https://doi.org/10.1000/ABC")
            == "10.1000/abc"
        )
        assert CrossrefClient.normalize_doi("DOI: 10.1000/xyz") == "10.1000/xyz"
