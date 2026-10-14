"""OCR Pipeline — image normalization + configured vision-role inference."""
from __future__ import annotations

from typing import Literal

import cv2
import numpy as np

from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel


class ImagePreprocessor:
    """Normalize image encoding with optional legacy binary enhancement."""

    def enhance(self, image: bytes, mode: Literal["raw", "binary"] = "binary") -> bytes:
        if mode not in {"raw", "binary"}:
            raise ValueError("OCR preprocessing mode must be 'raw' or 'binary'")
        decode_mode = cv2.IMREAD_UNCHANGED if mode == "raw" else cv2.IMREAD_GRAYSCALE
        try:
            img = cv2.imdecode(np.frombuffer(image, np.uint8), decode_mode)
        except cv2.error as exc:
            raise ValueError("无法解码图片") from exc
        if img is None:
            raise ValueError("无法解码图片")
        if mode == "raw" and img.dtype not in (np.uint8, np.uint16):
            raise ValueError(
                "Raw OCR normalization requires 8-bit or 16-bit pixels for lossless PNG"
            )

        if mode == "binary":
            # Preserve the legacy grayscale/blur/threshold/upscale path.
            img = cv2.GaussianBlur(img, (3, 3), 0)

            img = cv2.adaptiveThreshold(
                img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2,
            )

            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        encoded, png = cv2.imencode(".png", img)
        if not encoded:
            raise ValueError("无法编码图片为 PNG")
        return png.tobytes()


class OCRPipeline:
    """OCR: normalize the image, then ask the existing configured vision role."""

    def __init__(self, model: MiniCPMModel, config: TeXadaConfig):
        self.model = model
        self.config = config
        self.preprocessor = ImagePreprocessor()

    async def process(self, image: bytes) -> str:
        processed = self.preprocessor.enhance(image, mode=self.config.ocr_preprocessing)
        latex = await self.model.ocr_latex(processed)
        return latex
