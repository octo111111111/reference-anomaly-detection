from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reference_anomaly_detection.pipeline import print_cli_summary, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "一键检测：上传论文 PDF/Word，依次执行模块一至五，"
            "在命令行输出可读摘要，stdout 输出汇总 JSON"
        ),
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
        help="汇总 JSON 保存路径；省略则仅打印到 stdout",
    )
    parser.add_argument(
        "--save-intermediate",
        type=Path,
        metavar="DIR",
        help="可选：将各步骤 JSON 写入该目录",
    )
    parser.add_argument(
        "--skip-retraction",
        action="store_true",
        help="跳过撤稿检测（模块四）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="撤稿 SQLite 索引路径；省略时使用默认路径",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用 Crossref SQLite 本地缓存",
    )
    parser.add_argument(
        "--mailto",
        default="reference-anomaly-detection@example.com",
        help="Crossref polite pool 联系邮箱",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def progress(msg: str) -> None:
        print(msg, file=sys.stderr)

    try:
        report, intermediates = run_pipeline(
            args.file,
            file_type=args.file_type,
            mailto=args.mailto,
            cache_enabled=not args.no_cache,
            retraction_db=args.db,
            skip_retraction=args.skip_retraction,
            on_progress=progress,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    output = report.model_dump(mode="json")
    print_cli_summary(report)

    if args.save_intermediate:
        out_dir = args.save_intermediate
        out_dir.mkdir(parents=True, exist_ok=True)
        mapping = {
            "parse.json": intermediates["parse"],
            "extract.json": intermediates["extract"],
            "doi_checks.json": intermediates["doi_checks"],
        }
        if intermediates["retraction_checks"] is not None:
            mapping["retraction_checks.json"] = intermediates["retraction_checks"]
        for name, model in mapping.items():
            path = out_dir / name
            path.write_text(
                json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        summary_path = out_dir / "summary.json"
        summary_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"中间结果已写入: {out_dir}", file=sys.stderr)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"汇总已写入: {args.output}", file=sys.stderr)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
