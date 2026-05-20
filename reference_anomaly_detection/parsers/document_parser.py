from __future__ import annotations

import re
from pathlib import Path

import fitz
from docx import Document

from reference_anomaly_detection.models.schemas import (
    PaperParseInput,
    PaperParseResult,
)
from reference_anomaly_detection.parsers.citation_context_extractor import (
    extract_citation_contexts,
)
from reference_anomaly_detection.utils.paper_id import generate_paper_id

REFERENCE_HEADING_PATTERNS = [
    r"^references?\s*$",
    r"^bibliography\s*$",
    r"^literature\s+cited\s*$",
    r"^works?\s+cited\s*$",
    r"^参考文献\s*$",
    r"^引用文献\s*$",
]

REFERENCE_HEADING_RE = re.compile(
    "|".join(f"(?:{p})" for p in REFERENCE_HEADING_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)

ABSTRACT_START_RE = re.compile(
    r"^(?:abstract|summary|摘\s*要)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

KEYWORDS_RE = re.compile(
    r"^(?:keywords?|key\s+words|索引词|关键词)\s*[:：]?\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

SECTION_AFTER_ABSTRACT_RE = re.compile(
    r"^(?:\d+\.?\s*)?"
    r"(?:introduction|background|keywords?|key\s+words|"
    r"引言|前言|背景|关键词|index\s+terms)\b",
    re.IGNORECASE | re.MULTILINE,
)


class DocumentParser:
    """模块一：从 PDF / Word 抽取文本与结构信息。"""

    def parse(self, paper_input: PaperParseInput) -> PaperParseResult:
        path = Path(paper_input.file_path)
        if not path.is_file():
            raise FileNotFoundError(f"论文文件不存在: {path}")

        file_type = paper_input.file_type or path.suffix.lstrip(".").lower()
        if file_type == "doc":
            file_type = "docx"

        if file_type == "pdf":
            full_text, page_texts = self._extract_pdf(path)
        elif file_type == "docx":
            full_text, page_texts = self._extract_docx(path)
        else:
            raise ValueError(f"不支持的文件类型: {file_type}")

        title = self._extract_title(full_text, page_texts)
        abstract = self._extract_abstract(full_text)
        keywords = self._extract_keywords(full_text)
        ref_text, body_text = self._split_reference_section(full_text)
        citation_contexts = extract_citation_contexts(body_text)

        paper_id = paper_input.paper_id or generate_paper_id()

        return PaperParseResult(
            paper_id=paper_id,
            title=title,
            abstract=abstract,
            keywords=keywords,
            body_text=body_text,
            reference_section_text=ref_text,
            citation_contexts=citation_contexts,
        )

    def _extract_pdf(self, path: Path) -> tuple[str, list[str]]:
        doc = fitz.open(path)
        try:
            page_texts = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        full_text = "\n\n".join(page_texts)
        return full_text, page_texts

    def _extract_docx(self, path: Path) -> tuple[str, list[str]]:
        document = Document(path)
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        full_text = "\n\n".join(paragraphs)
        # Word 无真实分页，整篇视为单页块列表
        return full_text, [full_text] if full_text else []

    def _extract_title(self, full_text: str, page_texts: list[str]) -> str | None:
        if page_texts:
            first_page_lines = [
                ln.strip()
                for ln in page_texts[0].splitlines()
                if ln.strip() and len(ln.strip()) > 3
            ]
            skip_headers = {"abstract", "summary", "摘要", "keywords", "关键词"}
            for line in first_page_lines[:8]:
                lower = line.lower()
                if lower in skip_headers or len(line) > 300:
                    continue
                if re.match(r"^\d+$", line):
                    continue
                return line

        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        return lines[0] if lines else None

    def _extract_abstract(self, full_text: str) -> str | None:
        start_match = ABSTRACT_START_RE.search(full_text)
        if not start_match:
            return None

        after_heading = full_text[start_match.end() :].lstrip()
        end_match = SECTION_AFTER_ABSTRACT_RE.search(after_heading)
        abstract_text = (
            after_heading[: end_match.start()] if end_match else after_heading[:2500]
        )
        abstract_text = re.sub(r"\s+", " ", abstract_text).strip()
        return abstract_text or None

    def _extract_keywords(self, full_text: str) -> list[str]:
        match = KEYWORDS_RE.search(full_text)
        if not match:
            return []

        raw = match.group(1).strip()
        parts = re.split(r"[;；,，]\s*", raw)
        return [p.strip() for p in parts if p.strip()]

    def _split_reference_section(self, full_text: str) -> tuple[str | None, str]:
        match = None
        for m in REFERENCE_HEADING_RE.finditer(full_text):
            match = m

        if match is None:
            return None, full_text.strip()

        body_text = full_text[: match.start()].strip()
        ref_text = full_text[match.end() :].strip()
        return ref_text or None, body_text
