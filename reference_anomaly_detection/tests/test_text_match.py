from __future__ import annotations

from reference_anomaly_detection.services.text_match import (
    fts_query_from_title,
    normalize_text,
    text_similarity,
)


class TestTextMatch:
    def test_normalize_text(self) -> None:
        assert normalize_text("Hello, World!") == "hello world"

    def test_text_similarity(self) -> None:
        score = text_similarity(
            "Local government in Thailand",
            "Local government in Thailand: A way forward",
        )
        assert score is not None
        assert score > 0.8

    def test_fts_query_from_title(self) -> None:
        query = fts_query_from_title("Climate change and coastal zones")
        assert query is not None
        assert "climate" in query.lower()
