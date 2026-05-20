from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.checkers.retraction_checker import RetractionChecker
from reference_anomaly_detection.models.schemas import (
    ReferenceItem,
    RetractionCheckInput,
)
from reference_anomaly_detection.services.retraction_watch_index import (
    RetractionWatchIndex,
    RetractionWatchIndexError,
)
from reference_anomaly_detection.utils.paper_id import inherit_paper_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="撤稿文献检测（模块四）；paper_id 从模块二 JSON 继承",
    )
    parser.add_argument(
        "--from-extract",
        type=Path,
        required=True,
        help="模块二输出的 JSON（含 paper_id 与 references）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="检测结果 JSON 输出路径；省略则打印到 stdout",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="撤稿 SQLite 索引路径；省略时使用默认路径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    payload = json.loads(args.from_extract.read_text(encoding="utf-8"))
    try:
        paper_id = inherit_paper_id(payload, label="模块二 JSON")
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    try:
        index = RetractionWatchIndex(args.db or RetractionWatchIndex.default_db_path())
    except RetractionWatchIndexError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    references = [
        ReferenceItem.model_validate(item) for item in payload.get("references", [])
    ]
    result = RetractionChecker(index).check(
        RetractionCheckInput(paper_id=paper_id, references=references),
    )
    output = result.model_dump(mode="json")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写入: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
