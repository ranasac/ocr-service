"""Tests for image transformation utilities."""

import io

import numpy as np
import pytest
from PIL import Image

from app.image.transforms import (
    array_to_pil,
    convert_to_grayscale,
    denoise_image,
    normalize_image,
    preprocess_for_ocr,
    resize_image,
)


def _make_image(mode: str = "RGB", size: tuple = (200, 200)) -> Image.Image:
    return Image.new(mode, size, color=128)


def _image_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestResizeImage:
    def test_resizes_within_bounds(self):
        img = _make_image(size=(1000, 800))
        result = resize_image(img, 400, 400)
        assert result.width <= 400
        assert result.height <= 400

    def test_small_image_not_enlarged(self):
        img = _make_image(size=(50, 50))
        result = resize_image(img, 800, 800)
        # thumbnail does not enlarge
        assert result.size == (50, 50)


class TestConvertGrayscale:
    def test_rgb_to_l(self):
        img = _make_image("RGB")
        result = convert_to_grayscale(img)
        assert result.mode == "L"

    def test_l_stays_l(self):
        img = _make_image("L")
        result = convert_to_grayscale(img)
        assert result.mode == "L"


class TestNormalizeImage:
    def test_returns_image(self):
        img = _make_image("L")
        result = normalize_image(img)
        assert isinstance(result, Image.Image)


class TestDenoiseImage:
    def test_returns_image(self):
        img = _make_image("L")
        result = denoise_image(img)
        assert isinstance(result, Image.Image)


class TestPreprocessForOCR:
    def test_rgb_png(self, sample_image_bytes):
        arr = preprocess_for_ocr(sample_image_bytes, resize_width=64, resize_height=64)
        assert isinstance(arr, np.ndarray)
        assert arr.ndim == 2  # grayscale
        assert arr.dtype == np.uint8
        assert arr.shape[0] <= 64
        assert arr.shape[1] <= 64

    def test_rgba_png(self):
        img = Image.new("RGBA", (120, 120), (255, 0, 0, 128))
        data = _image_to_bytes(img)
        arr = preprocess_for_ocr(data)
        assert arr.ndim == 2

    def test_output_shape_respects_resize(self, sample_image_bytes):
        arr = preprocess_for_ocr(sample_image_bytes, resize_width=32, resize_height=32)
        assert arr.shape[0] <= 32
        assert arr.shape[1] <= 32


class TestArrayToPil:
    def test_2d_array(self, sample_array):
        img = array_to_pil(sample_array)
        assert img.mode == "L"
        assert img.size == (100, 100)

    def test_3d_array(self):
        arr = np.zeros((50, 60, 3), dtype=np.uint8)
        img = array_to_pil(arr)
        assert img.mode == "RGB"
