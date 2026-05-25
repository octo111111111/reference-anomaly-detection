from __future__ import annotations

import re

from rapidfuzz import fuzz


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def text_similarity(a: str | None, b: str | None) -> float | None:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return None
    return fuzz.token_set_ratio(na, nb) / 100.0


def fts_query_from_title(title: str | None, *, max_tokens: int = 8) -> str | None:
    """从题名生成 FTS5 查询串（OR 连接显著词）。"""
    normalized = normalize_text(title)
    if not normalized:
        return None
    tokens = [t for t in normalized.split() if len(t) >= 3][:max_tokens]
    if not tokens:
        tokens = normalized.split()[:max_tokens]
    if not tokens:
        return None
    escaped = []
    for token in tokens:
        safe = re.sub(r'["\'\\]', "", token)
        if safe:
            escaped.append(f'"{safe}"')
    return " OR ".join(escaped) if escaped else None
