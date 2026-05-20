from __future__ import annotations

from pathlib import Path

import pytest

from reference_anomaly_detection.models.schemas import PaperParseInput
from reference_anomaly_detection.parsers.citation_context_extractor import (
    extract_citation_contexts,
)
from reference_anomaly_detection.parsers.document_parser import DocumentParser


SAMPLE_TEXT = """Machine Learning for Reference Review

Abstract
We propose a pipeline for reference anomaly detection.

Keywords: machine learning; references; doi

1. Introduction
Prior studies demonstrated strong baselines [1] and extensions [2, 3].
See also (Wang, 2021) for related work.

2. Methods
Details are omitted here [1].

References
[1] Smith J. Example title. Journal A. 2020. doi:10.1000/test.1
[2] Doe A. Another paper. Nature. 2019. doi:10.1000/test.2
"""


class TestCitationContextExtractor:
    def test_extracts_bracket_and_author_year_citations(self) -> None:
        body = (
            "1. Introduction\n"
            "Prior work [1] and more [2, 3]. Also (Wang, 2021) noted this.\n"
        )
        contexts = extract_citation_contexts(body)
        markers = {c.citation_marker for c in contexts}
        assert "[1]" in markers
        assert "[2, 3]" in markers
        assert "(Wang, 2021)" in markers
        assert all(c.context for c in contexts)


class TestDocumentParserHelpers:
    def setup_method(self) -> None:
        self.parser = DocumentParser()

    def test_split_reference_section(self) -> None:
        ref, body = self.parser._split_reference_section(SAMPLE_TEXT)
        assert ref is not None
        assert "Smith J" in ref
        assert "doi:10.1000/test.1" in ref
        assert "References" not in body
        assert "[1]" in body

    def test_split_reference_section_numbered_heading(self) -> None:
        text = (
            "1. Introduction\nBody text [1].\n\n"
            "6. References\n"
            "[1] Smith J. Example. Journal. 2020.\n"
        )
        ref, body = self.parser._split_reference_section(text)
        assert ref is not None
        assert "Smith J" in ref
        assert "6. References" not in body

    def test_extract_abstract_and_keywords(self) -> None:
        abstract = self.parser._extract_abstract(SAMPLE_TEXT)
        keywords = self.parser._extract_keywords(SAMPLE_TEXT)
        assert abstract is not None
        assert "reference anomaly" in abstract
        assert "machine learning" in keywords
        assert "doi" in keywords


class TestDocumentParserIntegration:
    def test_parse_auto_generates_paper_id(self, sample_pdf: Path) -> None:
        result = DocumentParser().parse(
            PaperParseInput(file_path=sample_pdf, file_type="pdf")
        )
        assert result.paper_id.startswith("paper_")

    def test_parse_pdf(self, sample_pdf: Path) -> None:
        result = DocumentParser().parse(
            PaperParseInput(
                paper_id="test_pdf",
                file_path=sample_pdf,
                file_type="pdf",
            )
        )
        assert result.paper_id == "test_pdf"
        assert result.title
        assert result.abstract
        assert result.reference_section_text
        assert "doi:10.1000/example" in result.reference_section_text
        assert result.citation_contexts
        assert any(c.citation_marker == "[1]" for c in result.citation_contexts)

    def test_parse_docx(self, sample_docx: Path) -> None:
        result = DocumentParser().parse(
            PaperParseInput(
                paper_id="test_docx",
                file_path=sample_docx,
                file_type="docx",
            )
        )
        assert result.paper_id == "test_docx"
        assert result.reference_section_text
        assert "Smith J" in result.reference_section_text
        assert any(c.citation_marker == "[1]" for c in result.citation_contexts)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            DocumentParser().parse(
                PaperParseInput(
                    paper_id="missing",
                    file_path=tmp_path / "nope.pdf",
                    file_type="pdf",
                )
            )
