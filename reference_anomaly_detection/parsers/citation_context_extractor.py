from __future__ import annotations

import re

from reference_anomaly_detection.models.schemas import CitationContext

# 正文引用标记：[1]、[1-3]、(Smith, 2020) 等
BRACKET_CITATION_RE = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")
AUTHOR_YEAR_CITATION_RE = re.compile(
    r"\(([A-Z][A-Za-z\-']+(?:\s+et\s+al\.)?(?:\s+and\s+[A-Z][A-Za-z\-']+)?,\s*\d{4}[a-z]?)\)"
)

SECTION_HEADING_RE = re.compile(
    r"^(?:\d+\.?\s*)?"
    r"(Introduction|Background|Methods?|Materials? and Methods?|Results?|"
    r"Discussion|Conclusions?|References?|Bibliography|Acknowledgments?|"
    r"摘要|引言|背景|方法|结果|讨论|结论|参考文献|致谢)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

CONTEXT_WINDOW = 120


def _find_section_for_position(text: str, pos: int) -> str | None:
    last_section: str | None = None
    for match in SECTION_HEADING_RE.finditer(text):
        if match.start() > pos:
            break
        last_section = match.group(1)
    return last_section


def _make_context(text: str, start: int, end: int) -> str:
    ctx_start = max(0, start - CONTEXT_WINDOW)
    ctx_end = min(len(text), end + CONTEXT_WINDOW)
    snippet = text[ctx_start:ctx_end].replace("\n", " ")
    return re.sub(r"\s+", " ", snippet).strip()


def extract_citation_contexts(body_text: str) -> list[CitationContext]:
    """从正文中抽取引用标记及其上下文。"""
    if not body_text.strip():
        return []

    seen: set[tuple[str, int]] = set()
    contexts: list[CitationContext] = []

    patterns: list[tuple[re.Pattern[str], str]] = [
        (BRACKET_CITATION_RE, "bracket"),
        (AUTHOR_YEAR_CITATION_RE, "author_year"),
    ]

    for pattern, _kind in patterns:
        for match in pattern.finditer(body_text):
            marker = match.group(0)
            key = (marker, match.start())
            if key in seen:
                continue
            seen.add(key)

            section = _find_section_for_position(body_text, match.start())
            contexts.append(
                CitationContext(
                    citation_marker=marker,
                    context=_make_context(body_text, match.start(), match.end()),
                    section=section,
                )
            )

    contexts.sort(key=lambda c: body_text.find(c.citation_marker))
    return contexts
