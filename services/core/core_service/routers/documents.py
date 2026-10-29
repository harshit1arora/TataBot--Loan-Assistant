"""Document upload, metadata, signed URLs and the signed download route."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..errors import NotFoundError, ValidationAppError
from ..models import Document
from ..ratelimit import enforce
from ..schemas import DocumentView, SignedUrlResponse
from ..security import (
    Principal,
    create_download_token,
    require_customer,
    verify_download_token,
)
from ..services import documents as document_service
from ..services import underwriting
from ..storage import ObjectStore, build_store

router = APIRouter(tags=["documents"])


def _store(settings: Settings) -> ObjectStore:
    return build_store(settings)


def _view(document: Document) -> DocumentView:
    return DocumentView(
        document_id=document.id,
        doc_type=document.doc_type,
        status=document.status,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        extraction_confidence=document.extraction_confidence,
        requires_review=document.requires_review,
        verified_income_paise=document.verified_income_paise,
    )


@router.post("/v1/documents", response_model=DocumentView, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    application_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_customer),
) -> DocumentView:
    """Accept a document for the authenticated customer only."""
    enforce(request, settings)
    if application_id:
        underwriting.get_owned_application(db, application_id, principal.customer_id)

    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise ValidationAppError(
                f"File exceeds the {limit // (1024 * 1024)} MB limit.",
                details={"max_bytes": limit},
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    document = document_service.create(
        db,
        settings=settings,
        store=_store(settings),
        customer_id=principal.customer_id,
        application_id=application_id,
        doc_type=doc_type,
        filename=file.filename or "upload",
        declared_content_type=file.content_type,
        data=data,
    )
    return _view(document)


@router.get("/v1/documents/{document_id}", response_model=DocumentView)
def read_document(
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_customer),
) -> DocumentView:
    return _view(document_service.get_owned(db, document_id, principal.customer_id))


@router.get("/v1/documents/{document_id}/signed-url", response_model=SignedUrlResponse)
def signed_url(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_customer),
) -> SignedUrlResponse:
    """Mint a short-lived, single-purpose link. Ownership is checked before signing."""
    document_service.get_owned(db, document_id, principal.customer_id)
    token = create_download_token(document_id, principal.customer_id, settings)
    return SignedUrlResponse(url=f"/download/{token}", expires_in=settings.signed_url_ttl_seconds)


@router.get("/download/{token}")
def download(
    token: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Signed link redemption — no bearer token needed, the signature is the grant."""
    document_id, customer_id = verify_download_token(token, settings)
    document = db.get(Document, document_id)
    if document is None or document.customer_id != customer_id:
        raise NotFoundError("Document not found.")
    store = _store(settings)
    if not store.exists(document.storage_key):
        raise NotFoundError("Document content is unavailable.")
    # Streamed through the function rather than redirected, so the same code works
    # against local disk and a private bucket (no public object URLs, ever).
    return Response(
        content=store.read(document.storage_key),
        media_type=document.content_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
        },
    )
