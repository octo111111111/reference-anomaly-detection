from __future__ import annotations

from collections import defaultdict

from reference_anomaly_detection.models.schemas import (
    DoiCheckResult,
    DoiResolveResult,
    ReferenceItem,
    ReferenceFinding,
    RetractionCheckResult,
    RiskItem,
    RiskSummaryInput,
    RiskSummaryResult,
    RiskSummaryStats,
)

_MODULE_NAME = "reference_anomaly_detection"
_RESOLVED_SUFFIX = "-resolved"

_DOI_SEVERITY: dict[str, str] = {
    "doi_not_found": "high",
    "title_mismatch": "high",
    "api_error": "medium",
    "year_mismatch": "medium",
    "journal_mismatch": "medium",
    "title_possible_mismatch": "low",
    "missing_doi": "low",
}

_RETRACTION_SEVERITY: dict[str, str] = {
    "cites_retracted_work": "high",
    "cites_retracted_work_title_possible": "medium",
    "cites_retraction_notice": "medium",
}

_DOI_ACTIONS: dict[str, str] = {
    "missing_doi": "请作者补充或核对 DOI",
    "doi_not_found": "请作者核对 DOI 是否正确",
    "title_mismatch": "请作者核对参考文献题名与 DOI 是否对应",
    "year_mismatch": "请作者核对发表年份",
    "journal_mismatch": "请作者核对期刊名称",
    "title_possible_mismatch": "建议人工复核题名与 DOI 是否一致",
    "api_error": "Crossref 查询失败，建议稍后重试或人工复核",
}

_RETRACTION_ACTIONS: dict[str, str] = {
    "cites_retracted_work": "请编辑复核是否引用已撤稿原文，并确认正文是否已说明",
    "cites_retracted_work_title_possible": (
        "题名模糊匹配到可能已撤稿文献，请人工核对是否为同一篇并确认引用是否恰当"
    ),
    "cites_retraction_notice": "请确认引用撤稿通知文献是否符合写作规范",
}

_RETRACTION_CONFIDENCE: dict[str, float] = {
    "cites_retracted_work": 0.95,
    "cites_retracted_work_title_possible": 0.75,
    "cites_retraction_notice": 0.85,
}

_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

# 无 DOI 且已用题名检索 Crossref，但仍未解析出 DOI
_CROSSREF_TITLE_SEARCH_UNRESOLVED = frozenset(
    {"no_candidates", "low_score", "api_error"},
)


def _max_severity(*severities: str) -> str:
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))


def _location_for_refs(ref_ids: list[str]) -> str:
    if len(ref_ids) == 1:
        return f"References/{ref_ids[0]}"
    return "References"


def _partition_doi_checks(
    doi_checks: list[DoiCheckResult],
) -> tuple[dict[str, DoiCheckResult], dict[str, DoiCheckResult]]:
    primary: dict[str, DoiCheckResult] = {}
    resolved: dict[str, DoiCheckResult] = {}
    for check in doi_checks:
        if check.ref_id.endswith(_RESOLVED_SUFFIX):
            base_id = check.ref_id[: -len(_RESOLVED_SUFFIX)]
            resolved[base_id] = check
        else:
            primary[check.ref_id] = check
    return primary, resolved


class RiskReportBuilder:
    """模块五：汇总 DOI 与撤稿检测结果，生成统一风险报告。"""

    def build(self, paper_input: RiskSummaryInput) -> RiskSummaryResult:
        doi_primary, doi_resolved = _partition_doi_checks(paper_input.doi_checks)
        retraction_by_ref = {c.ref_id: c for c in paper_input.retraction_checks}
        resolve_by_ref = {r.ref_id: r for r in paper_input.doi_resolve_results}

        ref_ids = self._ordered_ref_ids(
            paper_input.references,
            paper_input.doi_checks,
            paper_input.retraction_checks,
        )

        summary = self._compute_stats(
            ref_ids,
            doi_primary,
            retraction_by_ref,
            resolve_by_ref,
            retraction_skipped=paper_input.retraction_check_skipped,
        )
        reference_findings = self._build_reference_findings(
            paper_input.references,
            ref_ids,
            resolve_by_ref,
            doi_primary,
            doi_resolved,
            retraction_by_ref,
        )
        risk_items = self._build_risk_items(
            summary,
            doi_primary,
            retraction_by_ref,
        )

        return RiskSummaryResult(
            module=_MODULE_NAME,
            paper_id=paper_input.paper_id,
            reference_findings=reference_findings,
            risk_items=risk_items,
            summary=summary,
            retraction_check_skipped=paper_input.retraction_check_skipped,
            retraction_skip_reason=paper_input.retraction_skip_reason,
        )

    @staticmethod
    def _ordered_ref_ids(
        references: list[ReferenceItem],
        doi_checks: list[DoiCheckResult],
        retraction_checks: list[RetractionCheckResult],
    ) -> list[str]:
        if references:
            return [r.ref_id for r in references]
        seen: list[str] = []
        for ref_id in (
            *[c.ref_id.removesuffix(_RESOLVED_SUFFIX) for c in doi_checks],
            *[c.ref_id for c in retraction_checks],
        ):
            if ref_id not in seen:
                seen.append(ref_id)
        return seen

    def _compute_stats(
        self,
        ref_ids: list[str],
        doi_by_ref: dict[str, DoiCheckResult],
        retraction_by_ref: dict[str, RetractionCheckResult],
        resolve_by_ref: dict[str, DoiResolveResult],
        *,
        retraction_skipped: bool,
    ) -> RiskSummaryStats:
        doi_mismatch_flags = {
            "title_mismatch",
            "year_mismatch",
            "journal_mismatch",
            "title_possible_mismatch",
        }
        doi_found = 0
        doi_missing = 0
        doi_not_found = 0
        doi_mismatch = 0
        doi_issue_count = 0
        retracted = 0
        retraction_notice = 0
        crossref_title_unresolved = 0

        for ref_id in ref_ids:
            resolve = resolve_by_ref.get(ref_id)
            if (
                resolve is not None
                and resolve.crossref_search_status in _CROSSREF_TITLE_SEARCH_UNRESOLVED
            ):
                crossref_title_unresolved += 1

        for ref_id in ref_ids:
            doi_check = doi_by_ref.get(ref_id)
            if doi_check is None:
                continue
            flag = doi_check.risk_flag
            if flag:
                doi_issue_count += 1
            if doi_check.doi_exists is True:
                doi_found += 1
            if flag == "missing_doi":
                doi_missing += 1
            elif flag == "doi_not_found":
                doi_not_found += 1
            elif flag in doi_mismatch_flags:
                doi_mismatch += 1

            if not retraction_skipped:
                retraction = retraction_by_ref.get(ref_id)
                if retraction is None:
                    continue
                if retraction.risk_flag in {
                    "cites_retracted_work",
                    "cites_retracted_work_title_possible",
                }:
                    retracted += 1
                elif retraction.risk_flag == "cites_retraction_notice":
                    retraction_notice += 1

        return RiskSummaryStats(
            total_references=len(ref_ids),
            doi_found_count=doi_found,
            doi_missing_count=doi_missing,
            doi_not_found_count=doi_not_found,
            doi_mismatch_count=doi_mismatch,
            doi_issue_count=doi_issue_count,
            crossref_title_search_unresolved_count=crossref_title_unresolved,
            retracted_reference_count=retracted,
            retraction_notice_count=retraction_notice,
        )

    def _build_reference_findings(
        self,
        references: list[ReferenceItem],
        ref_ids: list[str],
        resolve_by_ref: dict[str, DoiResolveResult],
        doi_primary: dict[str, DoiCheckResult],
        doi_resolved: dict[str, DoiCheckResult],
        retraction_by_ref: dict[str, RetractionCheckResult],
    ) -> list[ReferenceFinding]:
        ref_by_id = {r.ref_id: r for r in references}
        findings: list[ReferenceFinding] = []

        for index, ref_id in enumerate(ref_ids, start=1):
            ref = ref_by_id.get(ref_id)
            resolve = resolve_by_ref.get(ref_id)
            if resolve is None:
                if ref and ref.doi:
                    search_status = "not_needed"
                elif ref and not ref.title:
                    search_status = "skipped_no_title"
                else:
                    search_status = "unknown"
                resolved_doi = None
                resolve_score = None
            else:
                search_status = resolve.crossref_search_status
                resolved_doi = resolve.resolved_doi
                resolve_score = resolve.resolve_score

            primary_check = doi_primary.get(ref_id)
            resolved_check = doi_resolved.get(ref_id)
            retraction = retraction_by_ref.get(ref_id)

            findings.append(
                ReferenceFinding(
                    ref_id=ref_id,
                    reference_index=index,
                    has_reference_doi=bool(ref.doi) if ref else False,
                    crossref_title_search_status=search_status,
                    crossref_resolved_doi=resolved_doi,
                    crossref_resolve_score=resolve_score,
                    doi_risk_flag=primary_check.risk_flag if primary_check else None,
                    doi_check_from_resolve=resolved_check is not None,
                    doi_check_from_resolve_risk_flag=(
                        resolved_check.risk_flag if resolved_check else None
                    ),
                    retraction_risk_flag=(
                        retraction.risk_flag if retraction else None
                    ),
                    retraction_match_method=(
                        retraction.match_method if retraction else None
                    ),
                ),
            )

        return findings

    def _build_risk_items(
        self,
        stats: RiskSummaryStats,
        doi_by_ref: dict[str, DoiCheckResult],
        retraction_by_ref: dict[str, RetractionCheckResult],
    ) -> list[RiskItem]:
        items: list[RiskItem] = []
        doi_flag_counts: dict[str, int] = defaultdict(int)
        doi_flag_refs: dict[str, list[str]] = defaultdict(list)
        for ref_id, check in doi_by_ref.items():
            if check.risk_flag:
                doi_flag_counts[check.risk_flag] += 1
                doi_flag_refs[check.risk_flag].append(ref_id)

        retraction_flag_counts: dict[str, int] = defaultdict(int)
        retraction_flag_refs: dict[str, list[str]] = defaultdict(list)
        for ref_id, check in retraction_by_ref.items():
            if check.risk_flag:
                retraction_flag_counts[check.risk_flag] += 1
                retraction_flag_refs[check.risk_flag].append(ref_id)

        if doi_flag_counts or retraction_flag_counts:
            parts: list[str] = []
            overview_ref_ids: list[str] = []
            if doi_flag_counts:
                parts.append(
                    f"参考文献中 {stats.doi_issue_count} 条存在 DOI/元数据风险"
                )
                for refs in doi_flag_refs.values():
                    overview_ref_ids.extend(refs)
            retracted_doi = retraction_flag_counts.get("cites_retracted_work", 0)
            retracted_title = retraction_flag_counts.get(
                "cites_retracted_work_title_possible", 0
            )
            if retracted_doi or retracted_title:
                detail = []
                if retracted_doi:
                    detail.append(f"{retracted_doi} 条经 DOI 匹配")
                if retracted_title:
                    detail.append(f"{retracted_title} 条经题名模糊匹配")
                parts.append(
                    f"{stats.retracted_reference_count} 条引用可能为已撤稿原文（"
                    + "，".join(detail)
                    + "）"
                )
                for refs in retraction_flag_refs.values():
                    overview_ref_ids.extend(refs)
            if retraction_flag_counts.get("cites_retraction_notice"):
                parts.append(
                    f"{stats.retraction_notice_count} 条引用撤稿通知文献"
                )
            severities = [
                _DOI_SEVERITY[f]
                for f in doi_flag_counts
                if f in _DOI_SEVERITY
            ] + [
                _RETRACTION_SEVERITY[f]
                for f in retraction_flag_counts
                if f in _RETRACTION_SEVERITY
            ]
            severity = _max_severity(*severities) if severities else "low"
            actions = [
                _DOI_ACTIONS[f]
                for f in doi_flag_counts
                if f in _DOI_ACTIONS
            ] + [
                _RETRACTION_ACTIONS[f]
                for f in retraction_flag_counts
                if f in _RETRACTION_ACTIONS
            ]
            unique_ref_ids = list(dict.fromkeys(overview_ref_ids))
            items.append(
                RiskItem(
                    risk_type="reference_anomaly",
                    severity=severity,
                    confidence=self._overall_confidence(stats),
                    evidence="；".join(parts) + "。",
                    ref_ids=unique_ref_ids,
                    location=_location_for_refs(unique_ref_ids),
                    review_required=True,
                    suggested_action="；".join(dict.fromkeys(actions)),
                )
            )

        for flag, count in sorted(doi_flag_counts.items()):
            if count == 0 or flag not in _DOI_SEVERITY:
                continue
            ref_ids = doi_flag_refs[flag]
            items.append(
                RiskItem(
                    risk_type=f"doi_{flag}",
                    severity=_DOI_SEVERITY[flag],
                    confidence=min(0.95, 0.5 + 0.1 * count),
                    evidence=f"{count} 条参考文献标记为 {flag}",
                    ref_ids=ref_ids,
                    location=_location_for_refs(ref_ids),
                    review_required=flag
                    in {"doi_not_found", "title_mismatch", "api_error"},
                    suggested_action=_DOI_ACTIONS.get(flag, "请人工复核"),
                )
            )

        for flag, count in sorted(retraction_flag_counts.items()):
            if count == 0 or flag not in _RETRACTION_SEVERITY:
                continue
            ref_ids = retraction_flag_refs[flag]
            base_conf = _RETRACTION_CONFIDENCE.get(flag, 0.8)
            items.append(
                RiskItem(
                    risk_type=flag,
                    severity=_RETRACTION_SEVERITY[flag],
                    confidence=min(0.98, base_conf + 0.05 * (count - 1)),
                    evidence=self._retraction_evidence(flag, count, retraction_by_ref),
                    ref_ids=ref_ids,
                    location=_location_for_refs(ref_ids),
                    review_required=True,
                    suggested_action=_RETRACTION_ACTIONS.get(flag, "请人工复核"),
                )
            )

        return items

    @staticmethod
    def _retraction_evidence(
        flag: str,
        count: int,
        retraction_by_ref: dict[str, RetractionCheckResult],
    ) -> str:
        if flag == "cites_retracted_work_title_possible":
            examples = [
                c.matched_title
                for c in retraction_by_ref.values()
                if c.risk_flag == flag and c.matched_title
            ][:2]
            if examples:
                return (
                    f"{count} 条参考文献经题名模糊匹配到撤稿记录（示例："
                    + "；".join(examples)
                    + "），需人工确认"
                )
        return f"{count} 条参考文献标记为 {flag}"

    @staticmethod
    def _overall_confidence(stats: RiskSummaryStats) -> float:
        if stats.total_references == 0:
            return 0.0
        issue_refs = stats.doi_issue_count + stats.retracted_reference_count
        return round(min(0.99, 0.4 + issue_refs / stats.total_references * 0.5), 2)
