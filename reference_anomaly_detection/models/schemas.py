from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PaperParseInput(BaseModel):
    file_path: str | Path
    file_type: Literal["pdf", "docx", "doc"] | None = None
    paper_id: str | None = None

    @field_validator("file_path", mode="before")
    @classmethod
    def _path_to_str(cls, v: str | Path) -> str:
        return str(v)


class CitationContext(BaseModel):
    citation_marker: str
    context: str
    section: str | None = None


class PaperParseResult(BaseModel):
    paper_id: str
    title: str | None = None
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list)
    body_text: str = ""
    reference_section_text: str | None = None
    citation_contexts: list[CitationContext] = Field(default_factory=list)


class ReferenceExtractInput(BaseModel):
    paper_id: str
    reference_section_text: str | None = None


class ReferenceItem(BaseModel):
    ref_id: str
    raw_text: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publisher: str | None = None
    year: int | None = None
    doi: str | None = None
    citation_markers: list[str] = Field(default_factory=list)


class ReferenceExtractResult(BaseModel):
    paper_id: str
    references: list[ReferenceItem] = Field(default_factory=list)


class DoiCheckInput(BaseModel):
    paper_id: str
    references: list[ReferenceItem] = Field(default_factory=list)


class DoiCheckResult(BaseModel):
    ref_id: str
    doi: str | None = None
    doi_exists: bool | None = None
    metadata_match_score: float | None = None
    matched_title: bool | None = None
    matched_year: bool | None = None
    matched_journal: bool | None = None
    crossref_title: str | None = None
    crossref_journal: str | None = None
    risk_flag: str | None = None


class DoiCheckBatchResult(BaseModel):
    paper_id: str
    doi_checks: list[DoiCheckResult] = Field(default_factory=list)


class RetractionCheckInput(BaseModel):
    paper_id: str
    references: list[ReferenceItem] = Field(default_factory=list)


class RetractionCheckResult(BaseModel):
    ref_id: str
    doi: str | None = None
    is_retracted: bool = False
    notice_doi: str | None = None
    retraction_nature: str | None = None
    retraction_date: str | None = None
    reason: str | None = None
    risk_flag: str | None = None


class RetractionCheckBatchResult(BaseModel):
    paper_id: str
    retraction_checks: list[RetractionCheckResult] = Field(default_factory=list)


class RiskSummaryInput(BaseModel):
    paper_id: str
    references: list[ReferenceItem] = Field(default_factory=list)
    doi_checks: list[DoiCheckResult] = Field(default_factory=list)
    retraction_checks: list[RetractionCheckResult] = Field(default_factory=list)
    retraction_check_skipped: bool = False
    retraction_skip_reason: str | None = None


class RiskItem(BaseModel):
    risk_type: str
    severity: Literal["high", "medium", "low"]
    confidence: float
    evidence: str
    location: str = "References"
    review_required: bool = True
    suggested_action: str


class RiskSummaryStats(BaseModel):
    total_references: int = 0
    doi_found_count: int = 0
    doi_missing_count: int = 0
    doi_not_found_count: int = 0
    doi_mismatch_count: int = 0
    doi_issue_count: int = 0
    retracted_reference_count: int = 0
    retraction_notice_count: int = 0


class RiskSummaryResult(BaseModel):
    module: str = "reference_anomaly_detection"
    paper_id: str
    risk_items: list[RiskItem] = Field(default_factory=list)
    summary: RiskSummaryStats
    retraction_check_skipped: bool = False
    retraction_skip_reason: str | None = None
