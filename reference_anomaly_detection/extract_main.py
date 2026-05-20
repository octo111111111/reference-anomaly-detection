from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.models.schemas import ReferenceExtractInput
from reference_anomaly_detection.parsers.reference_extractor import ReferenceExtractor
from reference_anomaly_detection.utils.paper_id import generate_paper_id, inherit_paper_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="参考文献抽取与结构化（模块二）；paper_id 从模块一 JSON 继承",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reference-text",
        help="参考文献区原始文本（独立调试；会生成新 paper_id）",
    )
    group.add_argument(
        "--from-parse",
        type=Path,
        help="模块一输出的 JSON（继承 paper_id 与 reference_section_text）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="结构化结果 JSON 输出路径；省略则打印到 stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    parse_payload: dict | None = None
    if args.from_parse:
        parse_payload = json.loads(args.from_parse.read_text(encoding="utf-8"))
        ref_text = parse_payload.get("reference_section_text")
        if not ref_text:
            print(
                f"错误: {args.from_parse} 中缺少 reference_section_text",
                file=sys.stderr,
            )
            return 1
        reference_section_text = ref_text
        try:
            paper_id = inherit_paper_id(parse_payload, label="模块一 JSON")
        except ValueError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
    else:
        reference_section_text = args.reference_text
        paper_id = generate_paper_id()
        print(f"paper_id: {paper_id}", file=sys.stderr)

    paper_input = ReferenceExtractInput(
        paper_id=paper_id,
        reference_section_text=reference_section_text,
    )
    result = ReferenceExtractor().extract(paper_input)
    payload = result.model_dump(mode="json")

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
