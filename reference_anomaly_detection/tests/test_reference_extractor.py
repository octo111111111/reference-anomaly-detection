from __future__ import annotations

import json
from pathlib import Path

import pytest

from reference_anomaly_detection.models.schemas import (
    PaperParseInput,
    ReferenceExtractInput,
)
from reference_anomaly_detection.parsers.document_parser import DocumentParser
from reference_anomaly_detection.parsers.reference_extractor import (
    ReferenceExtractor,
    _expand_citation_markers,
    _extract_doi,
    _split_raw_entries,
)


SAMPLE_REFERENCES = """[1] Smith J. Example title. Journal A. 2020;1(1):1-10. doi:10.1000/test.1
[2] Doe A. Another paper. Nature. 2019;5:100-110. doi:10.1000/test.2
[3] Wang L, Chen X. Chinese study on parsing. 计算机学报. 2021. doi:10.1000/test.3
"""

MULTILINE_REFERENCES = """[1] Smith J. Example title. Journal A. 2020;1(1):1-10.
doi:10.1000/
broken.1
[2] Doe A. Second reference. Science. 2019. doi:10.1000/broken.2
"""


class TestReferenceExtractorHelpers:
    def test_expand_citation_markers(self) -> None:
        assert _expand_citation_markers("[1]") == ["[1]"]
        assert _expand_citation_markers("[2-3]") == ["[2]", "[3]"]
        assert _expand_citation_markers("[2, 3]") == ["[2]", "[3]"]

    def test_extract_doi_with_prefix_and_url(self) -> None:
        assert _extract_doi("doi:10.1000/abc.1") == "10.1000/abc.1"
        assert (
            _extract_doi("see https://doi.org/10.1000/xyz.2 for details")
            == "10.1000/xyz.2"
        )

    def test_split_raw_entries(self) -> None:
        entries = _split_raw_entries(SAMPLE_REFERENCES)
        assert len(entries) == 3
        assert entries[0][0] == ["[1]"]
        assert "Smith J" in entries[0][1]


class TestReferenceExtractor:
    def setup_method(self) -> None:
        self.extractor = ReferenceExtractor()

    def test_extract_numbered_references(self) -> None:
        result = self.extractor.extract(
            ReferenceExtractInput(
                paper_id="submission_001",
                reference_section_text=SAMPLE_REFERENCES,
            )
        )
        assert result.paper_id == "submission_001"
        assert len(result.references) == 3

        first = result.references[0]
        assert first.ref_id == "R001"
        assert first.citation_markers == ["[1]"]
        assert first.doi == "10.1000/test.1"
        assert first.year == 2020
        assert first.title == "Example title"
        assert first.journal == "Journal A"
        assert "Smith" in first.authors[0]

        second = result.references[1]
        assert second.ref_id == "R002"
        assert second.doi == "10.1000/test.2"
        assert second.year == 2019

    def test_empty_reference_section(self) -> None:
        result = self.extractor.extract(
            ReferenceExtractInput(
                paper_id="empty",
                reference_section_text=None,
            )
        )
        assert result.references == []

    def test_multiline_doi_repair(self) -> None:
        result = self.extractor.extract(
            ReferenceExtractInput(
                paper_id="multiline",
                reference_section_text=MULTILINE_REFERENCES,
            )
        )
        assert len(result.references) == 2
        assert result.references[0].doi == "10.1000/broken.1"
        assert result.references[1].doi == "10.1000/broken.2"

    def test_period_numbered_references(self) -> None:
        text = (
            "1. Smith J. First paper. Journal A. 2020. doi:10.1000/num.1\n"
            "2. Doe A. Second paper. Nature. 2019. doi:10.1000/num.2\n"
        )
        result = self.extractor.extract(
            ReferenceExtractInput(
                paper_id="numbered",
                reference_section_text=text,
            )
        )
        assert len(result.references) == 2
        assert result.references[0].citation_markers == ["[1]"]
        assert result.references[0].doi == "10.1000/num.1"

    def test_integration_with_document_parser(self, sample_pdf: Path) -> None:
        parsed = DocumentParser().parse(
            PaperParseInput(
                paper_id="integration",
                file_path=sample_pdf,
                file_type="pdf",
            )
        )
        assert parsed.reference_section_text
        extracted = self.extractor.extract(
            ReferenceExtractInput(
                paper_id="integration",
                reference_section_text=parsed.reference_section_text,
            )
        )
        assert len(extracted.references) >= 2
        dois = {ref.doi for ref in extracted.references if ref.doi}
        assert "10.1000/example.1" in dois or any(
            d and "10.1000/example" in d for d in dois
        )

    def test_from_parse_json_roundtrip(self, sample_pdf: Path, tmp_path: Path) -> None:
        parsed = DocumentParser().parse(
            PaperParseInput(
                paper_id="roundtrip",
                file_path=sample_pdf,
                file_type="pdf",
            )
        )
        parse_file = tmp_path / "parse.json"
        parse_file.write_text(
            json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
        payload = json.loads(parse_file.read_text(encoding="utf-8"))
        extracted = self.extractor.extract(
            ReferenceExtractInput(
                paper_id=payload["paper_id"],
                reference_section_text=payload["reference_section_text"],
            )
        )
        assert extracted.references
