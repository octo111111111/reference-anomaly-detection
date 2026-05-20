from __future__ import annotations

import re
from typing import Iterable

from reference_anomaly_detection.models.schemas import (
    ReferenceExtractInput,
    ReferenceExtractResult,
    ReferenceItem,
)

# 单条参考文献起始： [1]、[2-3]、1.、2.
_ENTRY_START_RE = re.compile(
    r"^\s*(?:\[(\d+(?:\s*[-–,]\s*\d+)*)\]|(\d+)\.)\s+",
    re.MULTILINE,
)

# DOI（含 doi:、URL、换行/空格打断）
_DOI_PREFIX_RE = re.compile(
    r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)\s*",
    re.IGNORECASE,
)
_DOI_BODY_RE = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+(?:[-._;()/:A-Za-z0-9]*)",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# 作者片段：Smith J. / Smith, J. / Wang L et al.
_AUTHOR_SEGMENT_RE = re.compile(
    r"^[\w\u4e00-\u9fff\-']+(?:\s+[\w\u4e00-\u9fff\-']+)*(?:,\s*[\w\u4e00-\u9fff\-']+|\s+[A-Z\u4e00-\u9fff]\.?)+"
    r"(?:\s+et\s+al\.?)?\.?$",
    re.IGNORECASE,
)


def _expand_citation_markers(marker: str) -> list[str]:
    """将 [2-3]、[2, 3] 展开为 [2], [3]。"""
    inner = marker.strip("[]").strip()
    if re.fullmatch(r"\d+", inner):
        return [f"[{inner}]"]
    parts = re.split(r"[-–,]\s*", inner)
    return [f"[{p.strip()}]" for p in parts if p.strip().isdigit()]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _repair_doi_breaks(text: str) -> str:
    """合并被换行或空格拆散的 DOI。"""
    text = _DOI_PREFIX_RE.sub("doi:", text)

    def _join(match: re.Match[str]) -> str:
        chunk = match.group(0)
        compact = re.sub(r"\s+", "", chunk)
        return compact

    return re.sub(
        r"doi:\s*10\.\d{4,9}/[\s\S]*?(?=\n\n|\n\s*(?:\[|\d+\.)|$)",
        _join,
        text,
        flags=re.IGNORECASE,
    )


def _merge_continuation_lines(text: str) -> str:
    """将不以序号开头的续行并入上一条。"""
    lines = text.splitlines()
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if merged:
                merged[-1] += " "
            continue
        if _ENTRY_START_RE.match(stripped) or not merged:
            merged.append(stripped)
        else:
            merged[-1] = f"{merged[-1]} {stripped}"
    return "\n".join(merged)


def _split_raw_entries(reference_section_text: str) -> list[tuple[list[str], str]]:
    """按序号切分，返回 (citation_markers, raw_text) 列表。"""
    text = reference_section_text.strip()
    if not text:
        return []

    text = _merge_continuation_lines(_repair_doi_breaks(text))
    matches = list(_ENTRY_START_RE.finditer(text))

    if not matches:
        return [([], _normalize_whitespace(text))]

    entries: list[tuple[list[str], str]] = []
    for index, match in enumerate(matches):
        marker_raw = match.group(1) or match.group(2)
        markers = (
            _expand_citation_markers(f"[{marker_raw}]")
            if match.group(1)
            else [f"[{marker_raw}]"]
        )
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = _normalize_whitespace(text[start:end])
        if raw:
            entries.append((markers, raw))
    return entries


def _extract_doi(raw_text: str) -> str | None:
    prefixed_patterns = (
        r"doi:\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
        r"https?://(?:dx\.)?doi\.org/\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
    )
    for pattern in prefixed_patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower().rstrip(".,;)")

    compact = re.sub(r"\s+", "", raw_text)
    match = _DOI_BODY_RE.search(compact)
    if not match:
        return None
    return match.group(0).lower().rstrip(".,;)")


def _extract_year(raw_text: str) -> int | None:
    without_doi = _DOI_BODY_RE.sub("", raw_text)
    years = [int(y) for y in _YEAR_RE.findall(without_doi)]
    if not years:
        return None
    # 优先取卷期前的年份（常见 2020;12(3): 或 . 2020.）
    for match in _YEAR_RE.finditer(without_doi):
        year = int(match.group(0))
        tail = without_doi[match.end() : match.end() + 4]
        if tail.startswith(";") or tail.startswith(":") or tail.startswith("("):
            return year
    return years[-1]


def _strip_doi_and_year_suffix(text: str, year: int | None) -> str:
    text = _DOI_PREFIX_RE.sub("", text)
    text = _DOI_BODY_RE.sub("", text)
    if year is not None:
        text = re.sub(rf"\b{year}\b[;:\d()\s\-–,]*.*$", "", text)
    return _normalize_whitespace(text.strip(" .;,"))


def _split_period_segments(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\.\s+", text) if p.strip()]
    return parts


def _parse_bibliographic_fields(
    raw_text: str, markers: list[str]
) -> tuple[list[str], str | None, str | None, int | None, str | None]:
    doi = _extract_doi(raw_text)
    year = _extract_year(raw_text)
    core = _strip_doi_and_year_suffix(raw_text, year)

    if markers:
        for marker in markers:
            core = re.sub(rf"^\[?{re.escape(marker.strip('[]'))}\]?\s*", "", core)

    segments = _split_period_segments(core)
    if not segments:
        return [], None, None, year, doi

    authors: list[str] = []
    index = 0
    while index < len(segments) and _AUTHOR_SEGMENT_RE.match(segments[index]):
        authors.append(segments[index].rstrip("."))
        index += 1
        if index >= len(segments) - 1:
            break

    remaining = segments[index:]
    title: str | None = None
    journal: str | None = None

    if len(remaining) >= 2:
        title = remaining[0]
        journal = remaining[1]
    elif len(remaining) == 1:
        title = remaining[0]

    return authors, title, journal, year, doi


def _make_ref_id(index: int) -> str:
    return f"R{index:03d}"


class ReferenceExtractor:
    """模块二：参考文献拆分与字段结构化（不访问外部数据库）。"""

    def extract(self, paper_input: ReferenceExtractInput) -> ReferenceExtractResult:
        text = paper_input.reference_section_text
        if not text or not text.strip():
            return ReferenceExtractResult(
                paper_id=paper_input.paper_id,
                references=[],
            )

        raw_entries = _split_raw_entries(text)
        references: list[ReferenceItem] = []

        for index, (markers, raw_text) in enumerate(raw_entries, start=1):
            authors, title, journal, year, doi = _parse_bibliographic_fields(
                raw_text, markers
            )
            full_raw = raw_text
            if markers:
                full_raw = f"{markers[0]} {raw_text}".strip()

            references.append(
                ReferenceItem(
                    ref_id=_make_ref_id(index),
                    raw_text=full_raw,
                    title=title,
                    authors=authors,
                    journal=journal,
                    publisher=None,
                    year=year,
                    doi=doi,
                    citation_markers=markers,
                )
            )

        return ReferenceExtractResult(
            paper_id=paper_input.paper_id,
            references=references,
        )


def references_to_records(references: Iterable[ReferenceItem]) -> list[dict]:
    """将参考文献列表转为字典记录，便于 pandas 等下游批量处理。"""
    return [ref.model_dump(mode="json") for ref in references]
