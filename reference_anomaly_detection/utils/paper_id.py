from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any


def generate_paper_id() -> str:
    """生成随机稿件 ID（CLI 未指定且无法从上游继承时使用）。"""
    return f"paper_{uuid.uuid4().hex[:12]}"


def paper_id_from_file(file_path: Path | str) -> str:
    """用论文文件名（不含扩展名）生成稿件 ID。"""
    stem = Path(file_path).stem
    safe = re.sub(r"[^\w\-]", "_", stem, flags=re.UNICODE).strip("_")
    return safe[:64] if safe else generate_paper_id()


def inherit_paper_id(
    upstream: dict[str, Any] | None,
    *,
    label: str = "上游 JSON",
) -> str:
    """从上游模块 JSON 读取 paper_id（流水线标准路径）。"""
    if upstream and upstream.get("paper_id"):
        return str(upstream["paper_id"])
    raise ValueError(f"{label} 缺少 paper_id，请先执行 reference-parse")


def resolve_paper_id(
    explicit: str | None,
    *,
    file_path: Path | str | None = None,
    upstream: dict[str, Any] | None = None,
) -> str:
    """解析稿件 ID（Python API / 测试用）：显式 > 上游 > 文件名 > 随机。"""
    if explicit:
        return explicit
    if upstream and upstream.get("paper_id"):
        return str(upstream["paper_id"])
    if file_path is not None:
        return paper_id_from_file(file_path)
    return generate_paper_id()
