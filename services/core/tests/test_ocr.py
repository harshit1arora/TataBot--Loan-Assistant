"""OCR pipeline: real engines where available, deterministic fakes in tests."""
from __future__ import annotations

from io import BytesIO

import pytest
from core_service.extractors import build_extractor, render_pdf_page
from core_service.ocr import (
    DisabledOcrProvider,
    FakeOcrProvider,
    build_ocr,
)

SALARY_TEXT = "Example Technologies Pvt Ltd\nEmployee Name: Asha Verma\nNet Pay: 85000"


def _font(size: int = 42):
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def payslip_png(net_pay: int = 85000) -> bytes:
    """A real image of a payslip, rendered with PIL so OCR has something to read."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 520), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    draw.text((50, 50), "Example Technologies Pvt Ltd", fill="black", font=font)
    draw.text((50, 150), "Payslip - March 2026", fill="black", font=font)
    draw.text((50, 250), "Employee Name: Asha Verma", fill="black", font=font)
    draw.text((50, 350), f"Net Pay: {net_pay}", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_fake_provider_reads_the_salary_line():
    extractor = build_extractor(ocr_provider=FakeOcrProvider(SALARY_TEXT, 0.95))
    result = extractor("image/png", payslip_png(), 0.75)

    assert result.income_paise == 8_500_000
    assert result.confidence >= 0.75
    assert result.requires_review is False
    assert result.fields["name"] == "Asha Verma"
    assert any("OCR" in note for note in result.notes)


def test_low_ocr_confidence_goes_to_review_not_to_a_guess():
    extractor = build_extractor(ocr_provider=FakeOcrProvider(SALARY_TEXT, 0.30), min_ocr_confidence=0.55)
    result = extractor("image/png", payslip_png(), 0.75)

    assert result.income_paise is None
    assert result.requires_review is True
    assert "below" in " ".join(result.notes)


def test_unreadable_document_produces_no_income():
    extractor = build_extractor(ocr_provider=FakeOcrProvider("", 0.0))
    result = extractor("image/png", payslip_png(), 0.75)
    assert result.income_paise is None
    assert result.requires_review is True


def test_disabled_ocr_routes_images_to_review():
    extractor = build_extractor(ocr_provider=DisabledOcrProvider())
    result = extractor("image/png", payslip_png(), 0.75)
    assert result.income_paise is None
    assert result.requires_review is True


def test_a_pdf_with_a_text_layer_does_not_need_ocr():
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 760, "Payslip - March 2026")
    pdf.drawString(72, 740, "Employee Name: Asha Verma")
    pdf.drawString(72, 720, "Net Pay: 85000")
    pdf.save()

    calls: list[int] = []

    class CountingOcr(FakeOcrProvider):
        def read(self, image_bytes: bytes):
            calls.append(1)
            return super().read(image_bytes)

    extractor = build_extractor(ocr_provider=CountingOcr("Net Pay: 12345", 0.99))
    result = extractor("application/pdf", buffer.getvalue(), 0.75)

    assert result.income_paise == 8_500_000, "the text layer is authoritative"
    assert calls == [], "OCR must not run when the PDF already has text"


def test_a_scanned_pdf_falls_back_to_ocr():
    """No text layer, so the page is rasterised and read by OCR."""
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    # A page with a mark but no text layer — what a scan looks like to a parser.
    pdf.rect(72, 600, 200, 100, stroke=1, fill=0)
    pdf.showPage()
    pdf.save()
    scanned = buffer.getvalue()

    if render_pdf_page(scanned) is None:
        pytest.skip("poppler (pdftoppm) not available for rasterising")

    extractor = build_extractor(ocr_provider=FakeOcrProvider(SALARY_TEXT, 0.95))
    result = extractor("application/pdf", scanned, 0.75)
    assert result.income_paise == 8_500_000


def test_auto_provider_selection():
    provider = build_ocr("auto")
    assert provider.name in {"rapidocr", "tesseract", "disabled"}
    assert build_ocr("disabled").name == "disabled"


@pytest.mark.skipif(build_ocr("auto").name != "rapidocr", reason="rapidocr not installed")
def test_real_ocr_reads_a_rendered_payslip():
    """Integration: the actual ONNX engine against a real image."""
    extractor = build_extractor(ocr_provider=build_ocr("rapidocr"), min_ocr_confidence=0.3)
    result = extractor("image/png", payslip_png(85000), 0.4)

    assert result.income_paise == 8_500_000, f"OCR read: {result.fields} / {result.notes}"
    assert result.confidence > 0.3
