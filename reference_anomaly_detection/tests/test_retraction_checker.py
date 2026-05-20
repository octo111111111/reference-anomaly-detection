from __future__ import annotations

import json
from pathlib import Path

import pytest

from reference_anomaly_detection.checkers.retraction_checker import RetractionChecker
from reference_anomaly_detection.models.schemas import (
    ReferenceItem,
    RetractionCheckInput,
)
from reference_anomaly_detection.services.retraction_watch_index import (
    RetractionWatchIndex,
    RetractionWatchIndexError,
)

SAMPLE_CSV = Path(__file__).parent / "data" / "retraction_watch_sample.csv"

ORIGINAL_DOI = "10.1080/23311886.2023.2268972"
RETRACTION_DOI = "10.1080/23311886.2024.2342626"


@pytest.fixture
def retraction_index(tmp_path: Path) -> RetractionWatchIndex:
    db_path = tmp_path / "retraction_test.sqlite"
    RetractionWatchIndex.build_from_csv(SAMPLE_CSV, db_path=db_path)
    return RetractionWatchIndex(db_path)


class TestRetractionWatchIndex:
    def test_build_and_lookup(self, retraction_index: RetractionWatchIndex) -> None:
        record = retraction_index.lookup_by_original_doi(ORIGINAL_DOI)
        assert record is not None
        assert record.retraction_doi == RETRACTION_DOI
        assert record.retraction_nature == "Retraction"

    def test_lookup_retraction_doi(self, retraction_index: RetractionWatchIndex) -> None:
        record = retraction_index.lookup_by_retraction_doi(RETRACTION_DOI)
        assert record is not None
        assert record.original_doi == ORIGINAL_DOI

    def test_missing_index_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RetractionWatchIndexError, match="撤稿索引不存在"):
            RetractionWatchIndex(tmp_path / "missing.sqlite")

    def test_empty_csv_raises(self, tmp_path: Path) -> None:
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("Title,OriginalPaperDOI\n", encoding="utf-8")
        with pytest.raises(RetractionWatchIndexError, match="未从 CSV 导入"):
            RetractionWatchIndex.build_from_csv(empty_csv, db_path=tmp_path / "e.sqlite")


class TestRetractionChecker:
    def test_cites_retracted_work(self, retraction_index: RetractionWatchIndex) -> None:
        checker = RetractionChecker(retraction_index)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R001",
                raw_text="ref",
                title="Local government in Thailand",
                doi=ORIGINAL_DOI,
            )
        )
        assert result.is_retracted is True
        assert result.risk_flag == "cites_retracted_work"
        assert result.notice_doi == RETRACTION_DOI
        assert result.retraction_nature == "Retraction"

    def test_cites_retraction_notice(self, retraction_index: RetractionWatchIndex) -> None:
        checker = RetractionChecker(retraction_index)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R002",
                raw_text="ref",
                doi=RETRACTION_DOI,
            )
        )
        assert result.is_retracted is False
        assert result.risk_flag == "cites_retraction_notice"
        assert result.notice_doi == RETRACTION_DOI

    def test_no_doi(self, retraction_index: RetractionWatchIndex) -> None:
        checker = RetractionChecker(retraction_index)
        result = checker.check_reference(
            ReferenceItem(ref_id="R003", raw_text="no doi ref")
        )
        assert result.is_retracted is False
        assert result.risk_flag is None

    def test_clean_doi(self, retraction_index: RetractionWatchIndex) -> None:
        checker = RetractionChecker(retraction_index)
        result = checker.check_reference(
            ReferenceItem(
                ref_id="R004",
                raw_text="ref",
                doi="10.1000/unknown.article",
            )
        )
        assert result.is_retracted is False
        assert result.risk_flag is None

    def test_batch_check(self, retraction_index: RetractionWatchIndex) -> None:
        checker = RetractionChecker(retraction_index)
        batch = checker.check(
            RetractionCheckInput(
                paper_id="test_batch",
                references=[
                    ReferenceItem(
                        ref_id="R001",
                        raw_text="a",
                        doi=ORIGINAL_DOI,
                    ),
                    ReferenceItem(ref_id="R002", raw_text="b"),
                ],
            )
        )
        assert batch.paper_id == "test_batch"
        assert len(batch.retraction_checks) == 2
        assert batch.retraction_checks[0].is_retracted is True
        assert batch.retraction_checks[1].risk_flag is None

    def test_extract_json_roundtrip(self, retraction_index: RetractionWatchIndex) -> None:
        payload = {
            "paper_id": "paper_test123",
            "references": [
                {
                    "ref_id": "R001",
                    "raw_text": "[1] Example.",
                    "doi": ORIGINAL_DOI,
                }
            ],
        }
        refs = [ReferenceItem.model_validate(r) for r in payload["references"]]
        batch = RetractionChecker(retraction_index).check(
            RetractionCheckInput(paper_id=payload["paper_id"], references=refs),
        )
        data = json.loads(json.dumps(batch.model_dump(mode="json")))
        assert data["retraction_checks"][0]["risk_flag"] == "cites_retracted_work"
