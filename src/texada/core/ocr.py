"""OCR Pipeline — OpenCV preprocessing + MiniCPM-V multimodal inference."""
from __future__ import annotations

import cv2
import numpy as np

from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel


class ImagePreprocessor:
    """OpenCV preprocessing pipeline — reduces model recognition difficulty."""

    def enhance(self, image: bytes) -> bytes:
        img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError("无法解码图片")

        # 1. Gaussian noise reduction
        img = cv2.GaussianBlur(img, (3, 3), 0)

        # 2. Adaptive thresholding (binary)
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 3. 2x upscale for better OCR
        img = cv2.resize(img, None, fx=2, fy=2,
                         interpolation=cv2.INTER_CUBIC)

        return cv2.imencode('.png', img)[1].tobytes()


class OCRPipeline:
    """OCR: preprocess → MiniCPM-V multimodal → validate."""

    def __init__(self, model: MiniCPMModel, config: TeXadaConfig):
        self.model = model
        self.config = config
        self.preprocessor = ImagePreprocessor()

    async def process(self, image: bytes) -> str:
        # Step 1: Preprocess (zero-model, ~10ms)
        processed = self.preprocessor.enhance(image)
        # Step 2: MiniCPM-V multimodal inference (~2-4s)
        latex = await self.model.ocr_latex(processed)
        return latex