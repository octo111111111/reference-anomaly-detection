from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.checkers.doi_metadata_checker import DoiMetadataChecker
from reference_anomaly_detection.models.schemas import DoiCheckInput, ReferenceItem
from reference_anomaly_detection.services.crossref_client import CrossrefClient
from reference_anomaly_detection.services.doi_resolver import DoiResolver
from reference_anomaly_detection.utils.paper_id import inherit_paper_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DOI 与 Crossref 元数据校验（模块三）；paper_id 从模块二 JSON 继承",
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
        help="校验结果 JSON 输出路径；省略则打印到 stdout",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用 Crossref SQLite 本地缓存",
    )
    parser.add_argument(
        "--mailto",
        default="zhangyuyue@bupt.edu.cn",
        help="Crossref polite pool 联系邮箱",
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

    references_raw = payload.get("references", [])
    references = [ReferenceItem.model_validate(item) for item in references_raw]

    client = CrossrefClient(
        mailto=args.mailto,
        cache_enabled=not args.no_cache,
    )
    resolver = DoiResolver(crossref_client=client)
    doi_resolve_results, resolved_dois = resolver.resolve_batch(references)
    checker = DoiMetadataChecker(crossref_client=client)
    result = checker.check(
        DoiCheckInput(paper_id=paper_id, references=references),
        resolved_dois=resolved_dois,
    )
    result = result.model_copy(update={"doi_resolve_results": doi_resolve_results})
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
