from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from reference_anomaly_detection.checkers.doi_metadata_checker import DoiMetadataChecker
from reference_anomaly_detection.checkers.retraction_checker import RetractionChecker
from reference_anomaly_detection.models.schemas import (
    DoiCheckInput,
    PaperParseInput,
    ReferenceExtractInput,
    RetractionCheckInput,
    RiskSummaryInput,
    RiskSummaryResult,
)
from reference_anomaly_detection.parsers.document_parser import DocumentParser
from reference_anomaly_detection.parsers.reference_extractor import ReferenceExtractor
from reference_anomaly_detection.reports.report_builder import RiskReportBuilder
from reference_anomaly_detection.services.crossref_client import CrossrefClient
from reference_anomaly_detection.services.doi_resolver import DoiResolver
from reference_anomaly_detection.services.retraction_watch_index import (
    RetractionWatchIndex,
    RetractionWatchIndexError,
)


def run_pipeline(
    file_path: Path | str,
    *,
    paper_id: str | None = None,
    file_type: str | None = None,
    mailto: str = "zhangyuyue@bupt.edu.cn",
    cache_enabled: bool = True,
    crossref_cache_path: Path | str | None = None,
    retraction_db: Path | str | None = None,
    skip_retraction: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[RiskSummaryResult, dict[str, Any]]:
    """从论文文件运行模块一至五，返回汇总结果与各步骤中间数据。"""
    path = Path(file_path)
    log = on_progress or (lambda _msg: None)

    log("模块一：解析论文…")
    parsed = DocumentParser().parse(
        PaperParseInput(
            file_path=path,
            file_type=file_type,
            paper_id=paper_id,
        ),
    )
    if not parsed.reference_section_text:
        raise ValueError("未识别到参考文献区，无法继续检测")

    log("模块二：结构化参考文献…")
    extracted = ReferenceExtractor().extract(
        ReferenceExtractInput(
            paper_id=parsed.paper_id,
            reference_section_text=parsed.reference_section_text,
        ),
    )
    if not extracted.references:
        raise ValueError("参考文献区未解析出任何条目")

    crossref = CrossrefClient(
        mailto=mailto,
        cache_enabled=cache_enabled,
        cache_path=crossref_cache_path,
    )

    log("书目解析：为无 DOI 条目检索 Crossref…")
    doi_resolve_results, resolved_dois = DoiResolver(crossref_client=crossref).resolve_batch(
        extracted.references,
    )

    log("模块三：DOI 与元数据校验…")
    doi_batch = DoiMetadataChecker(crossref_client=crossref).check(
        DoiCheckInput(
            paper_id=extracted.paper_id,
            references=extracted.references,
        ),
        resolved_dois=resolved_dois,
    )

    retraction_skipped = skip_retraction
    skip_reason: str | None = None
    retraction_batch = None

    if skip_retraction:
        skip_reason = "已通过 --skip-retraction 跳过"
        log("模块四：已跳过撤稿检测")
    else:
        log("模块四：撤稿文献检测…")
        try:
            index = RetractionWatchIndex(
                retraction_db or RetractionWatchIndex.default_db_path(),
            )
            retraction_batch = RetractionChecker(index).check(
                RetractionCheckInput(
                    paper_id=extracted.paper_id,
                    references=extracted.references,
                ),
                resolved_dois=resolved_dois,
            )
        except RetractionWatchIndexError as exc:
            retraction_skipped = True
            skip_reason = str(exc)
            log(f"模块四：跳过（{exc}）")

    log("模块五：生成风险汇总…")
    summary_input = RiskSummaryInput(
        paper_id=extracted.paper_id,
        references=extracted.references,
        doi_checks=doi_batch.doi_checks,
        doi_resolve_results=doi_resolve_results,
        retraction_checks=(
            retraction_batch.retraction_checks if retraction_batch else []
        ),
        retraction_check_skipped=retraction_skipped,
        retraction_skip_reason=skip_reason,
    )
    report = RiskReportBuilder().build(summary_input)

    intermediates: dict[str, Any] = {
        "parse": parsed,
        "extract": extracted,
        "doi_resolve": doi_resolve_results,
        "doi_checks": doi_batch,
        "retraction_checks": retraction_batch,
    }
    return report, intermediates


def format_cli_summary(report: RiskSummaryResult) -> str:
    """生成命令行可读摘要。"""
    stats = report.summary
    lines = [
        f"paper_id: {report.paper_id}",
        f"参考文献: {stats.total_references} 条",
        (
            f"DOI 校验: 存在 {stats.doi_found_count} 条 | "
            f"无 DOI {stats.doi_missing_count} 条 | "
            f"题名检索仍未解析 DOI {stats.crossref_title_search_unresolved_count} 条 | "
            f"DOI 不存在 {stats.doi_not_found_count} 条 | "
            f"元数据不一致 {stats.doi_mismatch_count} 条"
        ),
    ]
    if report.retraction_check_skipped:
        lines.append(f"撤稿检测: 已跳过（{report.retraction_skip_reason or '未知原因'}）")
    else:
        lines.append(
            f"撤稿检测: 引用已撤稿原文 {stats.retracted_reference_count} 条 | "
            f"引用撤稿通知 {stats.retraction_notice_count} 条"
        )
    if report.risk_items:
        lines.append(f"风险项: {len(report.risk_items)} 条")
        for item in report.risk_items:
            lines.append(f"  [{item.severity}] {item.evidence}")
    else:
        lines.append("风险项: 未发现需复核的参考文献风险信号")
    return "\n".join(lines)


def print_cli_summary(report: RiskSummaryResult, *, stream: Any = None) -> None:
    target = stream if stream is not None else sys.stderr
    print(format_cli_summary(report), file=target)
