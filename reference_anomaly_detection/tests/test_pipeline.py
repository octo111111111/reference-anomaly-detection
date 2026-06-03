from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reference_anomaly_detection.pipeline import format_cli_summary, run_pipeline
from reference_anomaly_detection.services.crossref_client import CrossrefWork
from reference_anomaly_detection.services.retraction_watch_index import RetractionWatchIndex

SAMPLE_CSV = Path(__file__).parent / "data" / "retraction_watch_sample.csv"


@pytest.fixture
def retraction_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "retraction.sqlite"
    RetractionWatchIndex.build_from_csv(SAMPLE_CSV, db_path=db_path)
    return db_path


def _mock_crossref_work(doi: str) -> CrossrefWork:
    return CrossrefWork(
        doi=doi,
        title=f"Crossref title for {doi}",
        journal="Test Journal",
        year=2020,
        authors=["Test Author"],
    )


class TestRunPipeline:
    def test_run_pipeline_pdf_mock_crossref(
        self,
        sample_pdf: Path,
        retraction_db: Path,
    ) -> None:
        client = MagicMock()
        client.normalize_doi.side_effect = lambda d: d.lower().strip()
        client.fetch_work.side_effect = lambda doi: _mock_crossref_work(doi)
        client.search_works_by_bibliographic.return_value = []

        with patch(
            "reference_anomaly_detection.pipeline.CrossrefClient",
            return_value=client,
        ):
            report, intermediates = run_pipeline(
                sample_pdf,
                retraction_db=retraction_db,
            )

        assert report.paper_id.startswith("paper_")
        assert report.summary.total_references >= 1
        assert intermediates["parse"].reference_section_text
        assert len(intermediates["extract"].references) >= 1
        assert len(intermediates["doi_checks"].doi_checks) >= 1
        assert intermediates["doi_resolve"] is not None
        assert intermediates["retraction_checks"] is not None
        summary_text = format_cli_summary(report)
        assert report.paper_id in summary_text

    def test_run_pipeline_skip_retraction(
        self,
        sample_pdf: Path,
    ) -> None:
        client = MagicMock()
        client.normalize_doi.side_effect = lambda d: d.lower().strip()
        client.fetch_work.side_effect = lambda doi: _mock_crossref_work(doi)
        client.search_works_by_bibliographic.return_value = []

        with patch(
            "reference_anomaly_detection.pipeline.CrossrefClient",
            return_value=client,
        ):
            report, _ = run_pipeline(sample_pdf, skip_retraction=True)

        assert report.retraction_check_skipped is True
        assert report.summary.retracted_reference_count == 0

    def test_run_main_cli(
        self,
        sample_pdf: Path,
        retraction_db: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from reference_anomaly_detection.run_main import main

        client = MagicMock()
        client.normalize_doi.side_effect = lambda d: d.lower().strip()
        client.fetch_work.side_effect = lambda doi: _mock_crossref_work(doi)
        client.search_works_by_bibliographic.return_value = []

        out_json = tmp_path / "summary.json"
        with patch(
            "reference_anomaly_detection.pipeline.CrossrefClient",
            return_value=client,
        ):
            code = main(
                [
                    "--file",
                    str(sample_pdf),
                    "--output",
                    str(out_json),
                    "--db",
                    str(retraction_db),
                    "--skip-retraction",
                ],
            )

        assert code == 0
        assert out_json.is_file()
        captured = capsys.readouterr()
        assert "paper_id:" in captured.err
        payload = json.loads(captured.out)
        assert payload["module"] == "reference_anomaly_detection"
        assert "summary" in payload
        assert "reference_findings" in payload
