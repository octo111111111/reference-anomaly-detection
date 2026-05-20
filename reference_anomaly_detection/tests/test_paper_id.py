from __future__ import annotations

from pathlib import Path

import pytest

from reference_anomaly_detection.utils.paper_id import (
    generate_paper_id,
    inherit_paper_id,
    paper_id_from_file,
    resolve_paper_id,
)


class TestPaperId:
    def test_generate_paper_id_format(self) -> None:
        value = generate_paper_id()
        assert value.startswith("paper_")
        assert len(value) > len("paper_")

    def test_paper_id_from_file(self) -> None:
        assert paper_id_from_file("uploads/submission_001.pdf") == "submission_001"

    def test_resolve_priority(self) -> None:
        assert resolve_paper_id("explicit", file_path="a.pdf") == "explicit"
        assert resolve_paper_id(None, upstream={"paper_id": "from_json"}) == "from_json"
        assert resolve_paper_id(None, file_path=Path("demo.docx")) == "demo"

    def test_resolve_generates_when_empty(self) -> None:
        value = resolve_paper_id(None)
        assert value.startswith("paper_")

    def test_inherit_paper_id(self) -> None:
        assert inherit_paper_id({"paper_id": "paper_abc"}) == "paper_abc"

    def test_inherit_paper_id_raises(self) -> None:
        with pytest.raises(ValueError, match="缺少 paper_id"):
            inherit_paper_id({})
