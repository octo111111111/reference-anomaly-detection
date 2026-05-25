from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from reference_anomaly_detection.services.text_match import normalize_text, text_similarity

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


class JournalMatcher:
    """期刊名模糊匹配（含别名表）。"""

    def __init__(self, aliases_path: Path | None = None) -> None:
        aliases = _load_yaml(aliases_path or _CONFIG_DIR / "journal_aliases.yaml")
        self._journal_aliases = self._build_alias_index(aliases)

    @staticmethod
    def _build_alias_index(aliases: dict[str, Any]) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for canonical, variants in aliases.items():
            names = {normalize_text(canonical)}
            if isinstance(variants, list):
                names.update(normalize_text(v) for v in variants if v)
            index[normalize_text(canonical)] = names
            for variant in variants if isinstance(variants, list) else []:
                key = normalize_text(variant)
                index.setdefault(key, set()).update(names)
        return index

    def _journal_candidates(self, name: str | None) -> set[str]:
        normalized = normalize_text(name)
        if not normalized:
            return set()
        candidates = {normalized}
        if normalized in self._journal_aliases:
            candidates.update(self._journal_aliases[normalized])
        for key, group in self._journal_aliases.items():
            if normalized in group or key == normalized:
                candidates.update(group)
                candidates.add(key)
        return candidates

    def similarity(
        self, ref_journal: str | None, other_journal: str | None
    ) -> float | None:
        if not ref_journal or not other_journal:
            return None
        ref_candidates = self._journal_candidates(ref_journal)
        other_candidates = self._journal_candidates(other_journal)
        best = 0.0
        for left in ref_candidates:
            for right in other_candidates:
                score = fuzz.token_set_ratio(left, right) / 100.0
                best = max(best, score)
        direct = text_similarity(ref_journal, other_journal)
        if direct is not None:
            best = max(best, direct)
        return best
