"""Income-document extraction.

Two adapters behind one interface:

* ``TextPdfExtractor`` reads the text layer of a PDF and pulls salary figures out with
  anchored patterns. It reports the confidence it actually achieved.
* ``ManualReviewExtractor`` never invents a number. When the text layer is missing
  (a scanned image), it returns no fields and asks for human review.

There is deliberately no adapter that fabricates data. If you need OCR for scans, add
one that calls a real provider (Textract / Document AI / a vendor API) and keep the
same contract: fields, confidence, and "requires review" below threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO


@dataclass
class ExtractionResult:
    fields: dict = field(default_factory=dict)
    confidence: float = 0.0
    income_paise: int | None = None
    requires_review: bool = True
    notes: list[str] = field(default_factory=list)


SALARY_PATTERNS = [
    (re.compile(r"net\s*pay[^0-9]{0,20}([0-9][0-9,]{3,})", re.I), 0.9),
    (re.compile(r"gross\s*(?:salary|pay)[^0-9]{0,20}([0-9][0-9,]{3,})", re.I), 0.75),
    (re.compile(r"(?:salary|income)[^0-9]{0,20}([0-9][0-9,]{3,})", re.I), 0.5),
]
NAME_PATTERN = re.compile(r"(?:employee\s*name|name)\s*[:\-]\s*([A-Za-z][A-Za-z .]{2,40})", re.I)
EMPLOYER_PATTERN = re.compile(r"(?:employer|company)\s*[:\-]\s*([A-Za-z0-9&.,'\- ]{3,60})", re.I)


def _parse_fields(text: str) -> ExtractionResult:
    """Shared pattern extraction for both the text-layer and OCR paths."""
    fields: dict = {}
    best_income: int | None = None
    best_confidence = 0.0
    for pattern, confidence in SALARY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = _to_paise(match.group(1))
        if value and confidence > best_confidence:
            best_income, best_confidence = value, confidence

    if match := NAME_PATTERN.search(text):
        fields["name"] = match.group(1).strip()
    if match := EMPLOYER_PATTERN.search(text):
        fields["employer"] = match.group(1).strip()
    if best_income:
        fields["monthly_income_paise"] = best_income

    return ExtractionResult(
        fields=fields,
        confidence=best_confidence,
        income_paise=best_income,
        requires_review=best_income is None,
        notes=[] if best_income else ["no salary figure found in the document text"],
    )


def _to_paise(raw: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return None
    value = int(digits)
    if value < 1_000 or value > 100_000_000:  # implausible monthly income
        return None
    return value * 100


class TextPdfExtractor:
    name = "text_pdf"

    def supports(self, content_type: str) -> bool:
        return content_type == "application/pdf"

    def extract(self, data: bytes, min_confidence: float) -> ExtractionResult:
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
        except Exception as exc:  # noqa: BLE001 - malformed PDF is a user problem
            return ExtractionResult(notes=[f"could not read pdf: {type(exc).__name__}"])

        if len(text.strip()) < 20:
            return ExtractionResult(
                notes=["no text layer found; manual review required"], requires_review=True
            )

        fields: dict = {}
        best_income: int | None = None
        best_confidence = 0.0
        for pattern, confidence in SALARY_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            value = _to_paise(match.group(1))
            if value and confidence > best_confidence:
                best_income, best_confidence = value, confidence

        if match := NAME_PATTERN.search(text):
            fields["name"] = match.group(1).strip()
        if match := EMPLOYER_PATTERN.search(text):
            fields["employer"] = match.group(1).strip()
        if best_income:
            fields["monthly_income_paise"] = best_income

        requires_review = best_confidence < min_confidence
        return ExtractionResult(
            fields=fields,
            confidence=best_confidence,
            income_paise=best_income,
            requires_review=requires_review,
            notes=[] if best_income else ["no salary figure found in the document text"],
        )


class OcrExtractor:
    """Reads an image (or a scanned PDF page) with OCR, then applies the same patterns.

    The field confidence is capped by the OCR engine's own confidence, so a shaky
    recognition cannot masquerade as a confident extraction.
    """

    name = "ocr"

    def __init__(self, provider, min_ocr_confidence: float = 0.55) -> None:
        self.provider = provider
        self.min_ocr_confidence = min_ocr_confidence

    def supports(self, content_type: str) -> bool:
        return self.provider.available()

    def extract(self, data: bytes, min_confidence: float) -> ExtractionResult:
        try:
            result = self.provider.read(data)
        except Exception as exc:  # noqa: BLE001 - a corrupt image must not fail the job
            return ExtractionResult(
                notes=[f"OCR could not read this file ({type(exc).__name__}); queued for review"],
                requires_review=True,
            )
        if not result.text.strip():
            return ExtractionResult(
                notes=[f"OCR ({result.provider}) produced no text; queued for review"],
                requires_review=True,
            )
        if result.confidence < self.min_ocr_confidence:
            return ExtractionResult(
                fields={},
                confidence=result.confidence,
                income_paise=None,
                requires_review=True,
                notes=[
                    f"OCR confidence {result.confidence:.2f} below {self.min_ocr_confidence:.2f}; "
                    "queued for review"
                ],
            )

        parsed = _parse_fields(result.text)
        parsed.confidence = min(parsed.confidence, result.confidence)
        parsed.requires_review = parsed.income_paise is None or parsed.confidence < min_confidence
        parsed.notes.append(f"read by OCR ({result.provider})")
        return parsed


class ManualReviewExtractor:
    name = "manual_review"

    def supports(self, content_type: str) -> bool:
        return True

    def extract(self, data: bytes, min_confidence: float) -> ExtractionResult:
        return ExtractionResult(
            fields={},
            confidence=0.0,
            income_paise=None,
            requires_review=True,
            notes=["no OCR available for this document; queued for review"],
        )


def build_extractor(ocr_provider=None, min_ocr_confidence: float = 0.55):
    """Returns `run(content_type, data, min_confidence)`.

    Order: PDF text layer first (cheap and exact), then OCR for images and scanned PDFs,
    then manual review. The OCR provider is injected so the core service decides which
    engine it has, and tests can supply a deterministic one.
    """
    text_pdf = TextPdfExtractor()
    manual = ManualReviewExtractor()
    ocr = OcrExtractor(ocr_provider, min_ocr_confidence) if ocr_provider else None

    def _run(content_type: str, data: bytes, min_confidence: float) -> ExtractionResult:
        if text_pdf.supports(content_type):
            result = text_pdf.extract(data, min_confidence)
            # A PDF with no text layer is a scan: try OCR on a rendered page.
            if result.income_paise is None and ocr is not None and ocr.supports(content_type):
                rendered = render_pdf_page(data)
                if rendered is not None:
                    ocr_result = ocr.extract(rendered, min_confidence)
                    if ocr_result.income_paise is not None or ocr_result.fields:
                        return ocr_result
            return result
        if ocr is not None and ocr.supports(content_type):
            return ocr.extract(data, min_confidence)
        return manual.extract(data, min_confidence)

    return _run


def render_pdf_page(data: bytes, dpi: int = 200) -> bytes | None:
    """Rasterise the first page of a PDF so OCR can read a scanned document.

    Uses poppler's pdftoppm when present; returns None when it is not, which routes the
    document to review rather than to a guess.
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if shutil.which("pdftoppm") is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "doc.pdf"
        pdf_path.write_bytes(data)
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell
                [  # noqa: S607 - resolved from PATH inside a controlled image
                    "pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                    str(pdf_path), str(Path(tmp) / "page"),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        pages = sorted(Path(tmp).glob("page*.png"))
        return pages[0].read_bytes() if pages else None
