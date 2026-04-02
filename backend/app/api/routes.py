from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.models.schemas import DocumentUploadResponse, PipelineRunRequest, PipelineRunResponse
from app.services.conflict_detector import ConflictDetector
from app.services.document_loader import DocumentLoader
from app.services.extractor import RuleExtractor
from app.services.notifier import DeviationNotifier
from app.services.parser import DocumentParser
from app.services.pipeline import PipelineService
from app.services.rule_engine import RuleEngine
from app.services.structurer import RuleStructurer
from app.storage.in_memory import InMemoryStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["ap-policy"])

settings = get_settings()
store = InMemoryStore()
pipeline_service = PipelineService(
    store=store,
    loader=DocumentLoader(),
    parser=DocumentParser(),
    extractor=RuleExtractor(settings=settings),
    structurer=RuleStructurer(),
    conflict_detector=ConflictDetector(),
    rule_engine=RuleEngine(),
    notifier=DeviationNotifier(settings=settings),
)


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    try:
        raw_bytes = await file.read()
        response = pipeline_service.upload_and_parse(filename=file.filename, raw_bytes=raw_bytes)
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Document upload failed error=%s", exc)
        raise HTTPException(status_code=500, detail="Failed to parse document") from exc


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict:
    document = pipeline_service.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": document.document_id,
        "filename": document.filename,
        "clauses_count": len(document.clauses),
        "clauses": document.clauses,
    }


@router.post("/pipeline/run/{document_id}", response_model=PipelineRunResponse)
def run_pipeline(document_id: str, request: PipelineRunRequest) -> PipelineRunResponse:
    try:
        return pipeline_service.run_pipeline(document_id=document_id, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline run failed document_id=%s error=%s", document_id, exc)
        raise HTTPException(status_code=500, detail="Pipeline execution failed") from exc


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
def get_run(run_id: str) -> PipelineRunResponse:
    run = pipeline_service.get_run(run_id=run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

