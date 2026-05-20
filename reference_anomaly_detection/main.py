from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.models.schemas import PaperParseInput
from reference_anomaly_detection.parsers.document_parser import DocumentParser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="论文文本与结构解析（模块一）；仅需论文文件，自动生成 paper_id",
    )
    parser.add_argument("--file", required=True, type=Path, help="论文文件路径")
    parser.add_argument(
        "--file-type",
        choices=["pdf", "docx", "doc"],
        help="文件类型，默认根据扩展名推断",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="解析结果 JSON 输出路径；省略则打印到 stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    paper_input = PaperParseInput(
        file_path=args.file,
        file_type=args.file_type,
    )
    result = DocumentParser().parse(paper_input)
    payload = result.model_dump(mode="json")

    print(f"paper_id: {result.paper_id}", file=sys.stderr)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已写入: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
