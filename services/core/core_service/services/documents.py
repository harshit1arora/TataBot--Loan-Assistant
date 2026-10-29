"""Document intake, extraction and the verified-income lookup.

The client never supplies a salary figure. Income used by underwriting comes from a
document that this service stored, extracted and (above the confidence threshold)
accepted.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import NotFoundError, ValidationAppError
from ..extractors import build_extractor
from ..models import Document, ExtractionJob
from ..ocr import build_ocr
from ..services import audit
from ..storage import ObjectStore

ALLOWED_DOC_TYPES = {"salary_slip", "bank_statement", "pan_card", "aadhaar"}


def create(
    db: Session,
    *,
    settings: Settings,
    store: ObjectStore,
    customer_id: str,
    application_id: str | None,
    doc_type: str,
    filename: str,
    declared_content_type: str | None,
    data: bytes,
) -> Document:
    if doc_type not in ALLOWED_DOC_TYPES:
        raise ValidationAppError(f"Unsupported document type. Allowed: {sorted(ALLOWED_DOC_TYPES)}")

    head = data[:16]
    from ..storage import sniff_content_type

    content_type = sniff_content_type(head, declared_content_type)
    stored = store.save(customer_id, content_type, data)

    document = Document(
        customer_id=customer_id,
        application_id=application_id,
        doc_type=doc_type,
        original_filename=(filename or "upload")[:255],
        content_type=content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        storage_key=stored.key,
        status="stored",
    )
    db.add(document)
    db.flush()

    if doc_type == "salary_slip":
        db.add(ExtractionJob(document_id=document.id))
    else:
        document.status = "stored"
    db.flush()

    audit.record(
        db,
        actor_type="customer",
        actor_id=customer_id,
        action="document.uploaded",
        entity_type="document",
        entity_id=document.id,
        metadata={"doc_type": doc_type, "size_bytes": stored.size_bytes, "sha256": stored.sha256},
    )
    return document


def get_owned(db: Session, document_id: str, customer_id: str) -> Document:
    """Ownership is checked here, not in the caller, so no route can forget it."""
    document = db.get(Document, document_id)
    if document is None or document.customer_id != customer_id:
        # Same error for "missing" and "someone else's" — no existence oracle.
        raise NotFoundError("Document not found.")
    return document


def process_next_job(db: Session, *, settings: Settings, store: ObjectStore) -> str | None:
    """Worker entry point: extract one pending salary slip. Returns the document id."""
    job = db.execute(
        select(ExtractionJob).where(ExtractionJob.status == "pending").order_by(ExtractionJob.created_at)
    ).scalars().first()
    if job is None:
        return None

    job.status = "processing"
    job.attempts += 1
    db.flush()

    document = db.get(Document, job.document_id)
    if document is None:
        job.status = "failed"
        job.last_error = "document missing"
        return None

    try:
        data = store.read(document.storage_key)
        extractor = build_extractor(
            ocr_provider=build_ocr(settings.ocr_provider),
            min_ocr_confidence=settings.ocr_min_confidence,
        )
        result = extractor(document.content_type, data, settings.min_extraction_confidence)
        document.extracted_fields = result.fields
        document.extraction_confidence = result.confidence
        document.requires_review = result.requires_review
        document.verified_income_paise = (
            result.income_paise if not result.requires_review else None
        )
        document.status = "extracted"
        job.status = "done"
        audit.record(
            db,
            actor_type="system",
            actor_id="worker",
            action="document.extracted",
            entity_type="document",
            entity_id=document.id,
            metadata={
                "confidence": result.confidence,
                "requires_review": result.requires_review,
                "notes": result.notes,
            },
        )
    except Exception as exc:  # noqa: BLE001 - a bad document must not kill the worker
        job.status = "failed"
        job.last_error = f"{type(exc).__name__}"
        document.status = "failed"
    return document.id


def verified_monthly_income_paise(db: Session, customer_id: str) -> int | None:
    """Latest income accepted from a salary slip, with no review flag outstanding."""
    row = db.execute(
        select(Document)
        .where(
            Document.customer_id == customer_id,
            Document.doc_type == "salary_slip",
            Document.status == "extracted",
            Document.requires_review.is_(False),
            Document.verified_income_paise.is_not(None),
        )
        .order_by(Document.created_at.desc())
    ).scalars().first()
    return row.verified_income_paise if row else None


def sanction_letter_for(db: Session, application_id: str) -> Document | None:
    return db.execute(
        select(Document).where(
            Document.application_id == application_id, Document.doc_type == "sanction_letter"
        )
    ).scalars().first()


def process_now(
    db: Session, *, settings: Settings, store: ObjectStore, document: Document
) -> Document:
    """Extract a single document inline.

    Used for small uploads where the customer is waiting for a decision. The queue
    (app/worker.py) still exists for retries, scans and anything slower than a request
    should reasonably block on.
    """
    from ..extractors import build_extractor
    from ..ocr import build_ocr

    data = store.read(document.storage_key)
    extractor = build_extractor(
        ocr_provider=build_ocr(settings.ocr_provider),
        min_ocr_confidence=settings.ocr_min_confidence,
    )
    result = extractor(document.content_type, data, settings.min_extraction_confidence)
    document.extracted_fields = result.fields
    document.extraction_confidence = result.confidence
    document.requires_review = result.requires_review
    document.verified_income_paise = result.income_paise if not result.requires_review else None
    document.status = "extracted"
    db.flush()
    audit.record(
        db,
        actor_type="system",
        actor_id="extraction",
        action="document.extracted",
        entity_type="document",
        entity_id=document.id,
        metadata={"confidence": result.confidence, "requires_review": result.requires_review},
    )
    return document
