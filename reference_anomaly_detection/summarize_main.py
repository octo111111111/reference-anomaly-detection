from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.models.schemas import (
    DoiCheckBatchResult,
    ReferenceExtractResult,
    RetractionCheckBatchResult,
    RiskSummaryInput,
)
from reference_anomaly_detection.pipeline import print_cli_summary
from reference_anomaly_detection.reports.report_builder import RiskReportBuilder
from reference_anomaly_detection.utils.paper_id import inherit_paper_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="风险汇总与报告生成（模块五）；合并模块二至四的 JSON 结果",
    )
    parser.add_argument(
        "--from-extract",
        type=Path,
        required=True,
        help="模块二 JSON（含 paper_id 与 references）",
    )
    parser.add_argument(
        "--from-doi",
        type=Path,
        required=True,
        help="模块三 JSON（含 doi_checks）",
    )
    parser.add_argument(
        "--from-retraction",
        type=Path,
        help="模块四 JSON；省略则视为未执行撤稿检测",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="汇总 JSON 输出路径；省略则打印到 stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    extract_payload = json.loads(args.from_extract.read_text(encoding="utf-8"))
    doi_payload = json.loads(args.from_doi.read_text(encoding="utf-8"))
    try:
        paper_id = inherit_paper_id(extract_payload, label="模块二 JSON")
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    doi_paper_id = doi_payload.get("paper_id")
    if doi_paper_id and doi_paper_id != paper_id:
        print(
            f"错误: 模块三 paper_id ({doi_paper_id}) 与模块二不一致 ({paper_id})",
            file=sys.stderr,
        )
        return 1

    extract_result = ReferenceExtractResult.model_validate(extract_payload)
    doi_result = DoiCheckBatchResult.model_validate(doi_payload)

    retraction_skipped = args.from_retraction is None
    skip_reason = "未提供模块四 JSON" if retraction_skipped else None
    retraction_checks: list = []
    if args.from_retraction:
        retraction_payload = json.loads(
            args.from_retraction.read_text(encoding="utf-8"),
        )
        retraction_result = RetractionCheckBatchResult.model_validate(
            retraction_payload,
        )
        if retraction_result.paper_id != paper_id:
            print(
                "错误: 模块四 paper_id 与模块二不一致",
                file=sys.stderr,
            )
            return 1
        retraction_checks = retraction_result.retraction_checks

    report = RiskReportBuilder().build(
        RiskSummaryInput(
            paper_id=paper_id,
            references=extract_result.references,
            doi_checks=doi_result.doi_checks,
            retraction_checks=retraction_checks,
            retraction_check_skipped=retraction_skipped,
            retraction_skip_reason=skip_reason,
        ),
    )
    output = report.model_dump(mode="json")
    print_cli_summary(report)

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
