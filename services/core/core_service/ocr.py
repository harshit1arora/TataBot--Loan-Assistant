"""OCR providers.

The extractor needs text from a document. Three ways to get it, in order of preference:

* **RapidOCR** (ONNX, pure pip) — real OCR on images and scanned pages, with a confidence
  score per line. Used by default when installed.
* **Tesseract** — used when the binary is present.
* **Disabled** — no OCR. Image documents then go to human review rather than being guessed.

A `FakeOcrProvider` exists for tests so the pipeline can be exercised deterministically.
Nothing here invents text: if OCR is unavailable or the engine is unsure, the document is
marked for review.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("core.ocr")


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float  # 0..1, averaged over recognised lines
    provider: str


class OcrProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def read(self, image_bytes: bytes) -> OcrResult: ...


class RapidOcrProvider:
    """ONNX-based OCR. ~1–2 s for a payslip-sized image on CPU."""

    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def _load(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read(self, image_bytes: bytes) -> OcrResult:
        from io import BytesIO

        import numpy as np
        from PIL import Image

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        result, _elapsed = self._load()(np.array(image))
        if not result:
            return OcrResult(text="", confidence=0.0, provider=self.name)

        lines: list[str] = []
        scores: list[float] = []
        for entry in result:
            # RapidOCR returns [box, text, score]
            if len(entry) >= 3:
                lines.append(str(entry[1]))
                try:
                    scores.append(float(entry[2]))
                except (TypeError, ValueError):
                    continue
        confidence = sum(scores) / len(scores) if scores else 0.0
        return OcrResult(text="\n".join(lines), confidence=confidence, provider=self.name)


class TesseractProvider:
    name = "tesseract"

    def available(self) -> bool:
        if shutil.which("tesseract") is None:
            return False
        try:
            import pytesseract  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def read(self, image_bytes: bytes) -> OcrResult:
        from io import BytesIO

        import pytesseract
        from PIL import Image

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = [word for word in data["text"] if word.strip()]
        scores = [
            float(conf) / 100.0
            for conf, word in zip(data["conf"], data["text"], strict=False)
            if word.strip() and str(conf) not in {"-1", ""}
        ]
        confidence = sum(scores) / len(scores) if scores else 0.0
        return OcrResult(text=" ".join(words), confidence=confidence, provider=self.name)


class DisabledOcrProvider:
    name = "disabled"

    def available(self) -> bool:
        return False

    def read(self, image_bytes: bytes) -> OcrResult:
        return OcrResult(text="", confidence=0.0, provider=self.name)


class FakeOcrProvider:
    """Deterministic provider for tests."""

    name = "fake"

    def __init__(self, text: str = "", confidence: float = 0.95) -> None:
        self._result = OcrResult(text=text, confidence=confidence, provider=self.name)

    def available(self) -> bool:
        return True

    def read(self, image_bytes: bytes) -> OcrResult:
        return self._result


def build_ocr(provider: str = "auto") -> OcrProvider:
    """`auto` picks the best available engine; anything unknown falls back to disabled."""
    choice = (provider or "auto").lower()
    if choice in ("auto", "rapidocr"):
        rapid = RapidOcrProvider()
        if rapid.available():
            return rapid
        if choice == "rapidocr":
            logger.warning("rapidocr requested but not installed; OCR disabled")
            return DisabledOcrProvider()
    if choice in ("auto", "tesseract"):
        tesseract = TesseractProvider()
        if tesseract.available():
            return tesseract
        if choice == "tesseract":
            logger.warning("tesseract requested but not installed; OCR disabled")
            return DisabledOcrProvider()
    return DisabledOcrProvider()
