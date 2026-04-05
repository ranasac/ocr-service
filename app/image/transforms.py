"""Image transformation utilities."""

import io
import logging

import numpy as np
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


def resize_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Resize image while maintaining aspect ratio (fit within width×height)."""
    img.thumbnail((width, height), Image.LANCZOS)
    return img


def convert_to_grayscale(img: Image.Image) -> Image.Image:
    """Convert image to grayscale (L mode)."""
    return img.convert("L")


def normalize_image(img: Image.Image) -> Image.Image:
    """Auto-contrast and deskew preparation."""
    return ImageOps.autocontrast(img)


def denoise_image(img: Image.Image) -> Image.Image:
    """Apply mild denoising filter."""
    return img.filter(ImageFilter.MedianFilter(size=3))


def preprocess_for_ocr(
    image_bytes: bytes,
    resize_width: int = 800,
    resize_height: int = 800,
) -> np.ndarray:
    """Full OCR preprocessing pipeline.

    Steps:
      1. Decode image bytes → PIL Image
      2. Convert to grayscale
      3. Auto-contrast normalisation
      4. Resize to target dimensions
      5. Mild denoising
      6. Convert to numpy array

    Returns:
        numpy array of shape (H, W) with dtype uint8.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Convert RGBA/P to RGB first, then grayscale
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img = convert_to_grayscale(img)
    img = normalize_image(img)
    img = resize_image(img, resize_width, resize_height)
    img = denoise_image(img)

    arr = np.array(img, dtype=np.uint8)
    logger.debug("Preprocessed image: shape=%s dtype=%s", arr.shape, arr.dtype)
    return arr


def array_to_pil(array: np.ndarray) -> Image.Image:
    """Convert numpy array back to PIL Image."""
    if array.ndim == 2:
        return Image.fromarray(array, mode="L")
    return Image.fromarray(array)
