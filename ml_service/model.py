"""OCR model wrapper.

Uses pytesseract (open-source Tesseract OCR engine) as the default lightweight
model.  The model is configurable via environment variables so that it can be
swapped out for a managed service (SageMaker, Azure ML, Vertex AI) without
code changes.
"""

import io
import logging
import time
from typing import Any, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _load_pytesseract():
    """Lazy import so the service starts even without tesseract installed."""
    try:
        import pytesseract
        return pytesseract
    except ImportError:
        logger.warning("pytesseract not available – using mock OCR")
        return None


class OCRModel:
    """Thin wrapper around pytesseract with configurable page-segmentation mode."""

    def __init__(self, lang: str = "eng", psm: int = 6) -> None:
        self._lang = lang
        self._psm = psm
        self._tess = _load_pytesseract()

    def predict(self, array: np.ndarray) -> dict[str, Any]:
        """Run OCR on a preprocessed numpy array.

        Args:
            array: Grayscale uint8 array of shape (H, W).

        Returns:
            dict with keys: text, confidence, words
        """
        start = time.perf_counter()

        if self._tess is None:
            # Mock response when tesseract is not installed
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "text": "[OCR mock – install tesseract for real results]",
                "confidence": None,
                "words": [],
                "processing_time_ms": elapsed_ms,
            }

        img = Image.fromarray(array) if array.ndim == 2 else Image.fromarray(array, "RGB")
        config = f"--psm {self._psm} --oem 3"

        try:
            data = self._tess.image_to_data(
                img,
                lang=self._lang,
                config=config,
                output_type=self._tess.Output.DICT,
            )
            text = self._tess.image_to_string(img, lang=self._lang, config=config).strip()

            # Build word-level metadata
            words = []
            for i, word in enumerate(data["text"]):
                if word.strip():
                    conf = data["conf"][i]
                    words.append({
                        "word": word,
                        "confidence": float(conf) if conf != -1 else None,
                        "bbox": {
                            "left": data["left"][i],
                            "top": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                        },
                    })

            avg_conf: Optional[float] = None
            valid_confs = [w["confidence"] for w in words if w["confidence"] is not None]
            if valid_confs:
                avg_conf = sum(valid_confs) / len(valid_confs)

        except Exception as exc:
            logger.exception("Tesseract error: %s", exc)
            text = ""
            words = []
            avg_conf = None

        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "text": text,
            "confidence": avg_conf,
            "words": words,
            "processing_time_ms": elapsed_ms,
        }


# Module-level singleton
_model: Optional[OCRModel] = None


def get_model() -> OCRModel:
    global _model
    if _model is None:
        _model = OCRModel()
    return _model
