from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reference_anomaly_detection.services.retraction_watch_index import (
    RetractionWatchIndex,
    RetractionWatchIndexError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 Retraction Watch CSV 构建本地撤稿 SQLite 索引",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Retraction Watch 数据库 CSV 文件路径",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="输出 SQLite 路径；省略时使用 config/retraction.yaml 默认路径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        db_path = RetractionWatchIndex.build_from_csv(args.csv, db_path=args.db)
    except RetractionWatchIndexError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"索引已构建: {db_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
