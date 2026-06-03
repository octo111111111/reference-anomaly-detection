from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from reference_anomaly_detection.api.settings import get_settings
from reference_anomaly_detection.models.schemas import RiskSummaryResult
from reference_anomaly_detection.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc"}


def _infer_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".doc":
        return "docx"
    return suffix.lstrip(".")


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    retraction_ok = settings.retraction_db.is_file()
    return {
        "status": "ok" if retraction_ok else "degraded",
        "service": "reference-anomaly-detection",
        "retraction_index": {
            "path": str(settings.retraction_db),
            "ready": retraction_ok,
        },
    }


@router.post("/v1/reference-check", response_model=RiskSummaryResult)
async def reference_check(
    file: UploadFile = File(...),
    paper_id: str | None = Form(default=None),
    skip_retraction: bool = Form(default=False),
) -> RiskSummaryResult:
    settings = get_settings()

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {suffix}，仅支持 {', '.join(sorted(_ALLOWED_SUFFIXES))}",
        )

    settings.upload_tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ref-check-", dir=settings.upload_tmp_dir))
    dest = tmp_dir / Path(file.filename).name

    try:
        total = 0
        with dest.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小限制 ({settings.max_upload_bytes} 字节)",
                    )
                handle.write(chunk)

        logger.info(
            "reference-check start paper_id=%s file=%s size=%d",
            paper_id,
            file.filename,
            total,
        )

        report, _ = run_pipeline(
            dest,
            paper_id=paper_id,
            file_type=_infer_file_type(file.filename),
            mailto=settings.crossref_mailto,
            cache_enabled=settings.cache_enabled,
            crossref_cache_path=settings.crossref_cache_path,
            retraction_db=settings.retraction_db,
            skip_retraction=skip_retraction,
            on_progress=lambda msg: logger.info("%s", msg),
        )
        return report
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
