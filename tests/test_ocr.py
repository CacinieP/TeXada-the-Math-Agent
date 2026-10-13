"""Image transport contracts for raw and legacy binary OCR preprocessing."""

import json
from unittest.mock import AsyncMock, Mock

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from texada.config import SAVED_CONFIG_FIELDS, TeXadaConfig, save_config_updates
from texada.core.model import MiniCPMModel
from texada.core.ocr import ImagePreprocessor, OCRPipeline

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode_image(image, extension=".png"):
    ok, encoded = cv2.imencode(extension, image)
    assert ok
    return encoded.tobytes()


def decode_image(image):
    decoded = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded is not None
    return decoded


def test_ocr_preprocessing_defaults_to_binary_and_raw_is_explicit_and_persisted(
    tmp_path, monkeypatch,
):
    assert TeXadaConfig().ocr_preprocessing == "binary"
    assert "ocr_preprocessing" in SAVED_CONFIG_FIELDS
    monkeypatch.setenv("TEXADA_OCR_PREPROCESSING", "raw")
    assert TeXadaConfig().ocr_preprocessing == "raw"
    saved = save_config_updates({"ocr_preprocessing": "raw"}, data_dir=tmp_path)
    assert saved.ocr_preprocessing == "raw"
    assert json.loads((tmp_path / "config.json").read_text())["ocr_preprocessing"] == "raw"


def test_ocr_preprocessing_rejects_unknown_modes():
    with pytest.raises(ValidationError):
        TeXadaConfig(ocr_preprocessing="soft")
    with pytest.raises(ValueError, match="preprocessing mode"):
        ImagePreprocessor().enhance(b"not an image", mode="soft")


@pytest.mark.parametrize("channels", [1, 3, 4])
def test_raw_png_preserves_dimensions_pixels_color_and_alpha(channels):
    shape = (9, 13) if channels == 1 else (9, 13, channels)
    pixels = np.arange(np.prod(shape), dtype=np.uint8).reshape(shape)
    image = encode_image(pixels)

    processed = ImagePreprocessor().enhance(image, mode="raw")

    assert processed.startswith(PNG_SIGNATURE)
    actual = decode_image(processed)
    assert actual.shape == pixels.shape
    assert actual.dtype == pixels.dtype
    np.testing.assert_array_equal(actual, pixels)


def test_raw_jpeg_is_png_with_identical_decoded_pixels_and_dimensions():
    pixels = np.arange(17 * 23 * 3, dtype=np.uint8).reshape((17, 23, 3))
    jpeg = encode_image(pixels, ".jpg")

    processed = ImagePreprocessor().enhance(jpeg, mode="raw")

    assert processed.startswith(PNG_SIGNATURE)
    assert decode_image(processed).shape == pixels.shape
    # JPEG has already lost detail at encoding; raw normalization introduces no
    # further pixel changes to the decoded input.
    np.testing.assert_array_equal(decode_image(processed), decode_image(jpeg))


def test_raw_png_preserves_16_bit_pixel_values():
    pixels = np.arange(9 * 13, dtype=np.uint16).reshape((9, 13)) * 257

    processed = ImagePreprocessor().enhance(encode_image(pixels), mode="raw")

    actual = decode_image(processed)
    assert actual.dtype == np.uint16
    np.testing.assert_array_equal(actual, pixels)


def test_raw_rejects_float_pixels_instead_of_silently_quantizing_to_png():
    pixels = np.linspace(0, 1, 9 * 13, dtype=np.float32).reshape((9, 13))
    tiff = encode_image(pixels, ".tiff")

    with pytest.raises(ValueError, match="lossless PNG"):
        ImagePreprocessor().enhance(tiff, mode="raw")


@pytest.mark.parametrize("mode", ["raw", "binary"])
@pytest.mark.parametrize("bad_image", [b"", b"not an image"])
def test_preprocessing_rejects_undecodable_images(mode, bad_image):
    with pytest.raises(ValueError, match="无法解码图片"):
        ImagePreprocessor().enhance(bad_image, mode=mode)


def test_default_binary_preserves_legacy_grayscale_and_double_dimensions():
    pixels = np.arange(13 * 17 * 3, dtype=np.uint8).reshape((13, 17, 3))
    image = encode_image(pixels)
    preprocessor = ImagePreprocessor()

    processed = preprocessor.enhance(image)

    assert processed.startswith(PNG_SIGNATURE)
    actual = decode_image(processed)
    assert actual.shape == (26, 34)
    assert processed == preprocessor.enhance(image, mode="binary")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["raw", "binary"])
async def test_pipeline_uses_configured_preprocessing_and_same_single_checkpoint(tmp_path, mode):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="openai_compatible",
        openai_base_url="https://api.modelbest.cn/v1",
        openai_api_key="test-placeholder",
        openai_model_name="MiniCPM-V-4.7-1B",
        openai_vision_model_name="",
        ocr_preprocessing=mode,
    )
    model = MiniCPMModel(config)
    model.ocr_latex = AsyncMock(return_value=r"\frac{a}{b}")
    pipeline = OCRPipeline(model, config)
    pipeline.preprocessor.enhance = Mock(wraps=pipeline.preprocessor.enhance)
    pixels = np.arange(11 * 15 * 3, dtype=np.uint8).reshape((11, 15, 3))
    image = encode_image(pixels)

    result = await pipeline.process(image)

    assert result == r"\frac{a}{b}"
    assert pipeline.model is model
    assert model.model == model._vision_model == "MiniCPM-V-4.7-1B"
    pipeline.preprocessor.enhance.assert_called_once_with(image, mode=mode)
    model.ocr_latex.assert_awaited_once()
    sent_image = model.ocr_latex.await_args.args[0]
    assert sent_image.startswith(PNG_SIGNATURE)
    actual = decode_image(sent_image)
    if mode == "raw":
        np.testing.assert_array_equal(actual, pixels)
    else:
        assert actual.shape == (22, 30)


@pytest.mark.asyncio
async def test_pipeline_rejects_bad_input_before_inference(tmp_path):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    model.ocr_latex = AsyncMock()
    pipeline = OCRPipeline(model, TeXadaConfig(ocr_preprocessing="raw"))

    with pytest.raises(ValueError, match="无法解码图片"):
        await pipeline.process(b"bad input")

    model.ocr_latex.assert_not_awaited()
