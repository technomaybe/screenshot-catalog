import os
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
from config import TESSERACT_CMD

if TESSERACT_CMD is not None:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Tesseract config:
#   --oem 3  = LSTM neural net engine (best accuracy)
#   -c preserve_interword_spaces=1  = keeps spacing intact
# Page-segmentation modes (psm) are chosen per pass below:
#   psm 6  = assume a uniform block of text  (good for documents/emails)
#   psm 11 = sparse text, find as much as possible in any order
#            (good for scattered UI labels, chart legends, buttons)
_BASE_CONFIG = "--oem 3 -c preserve_interword_spaces=1"

# Minimum dimension below which we upscale before OCR.
_MIN_DIMENSION = 1000

# Below this mean brightness (0-255) an image is treated as "dark mode",
# so the primary OCR pass runs on an inverted copy.
_DARK_THRESHOLD = 128

# Set OCR_FAST=1 to fall back to the old single-pass behaviour (faster,
# but misses light-on-dark text such as dark-mode UIs and chart labels).
_FAST = os.environ.get("OCR_FAST", "").strip().lower() in ("1", "true", "yes")


def _to_grayscale(img: Image.Image) -> Image.Image:
    """Normalise mode, upscale small images, and convert to greyscale."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if min(w, h) < _MIN_DIMENSION:
        scale = _MIN_DIMENSION / min(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img.convert("L")


def _enhance(gray: Image.Image) -> Image.Image:
    """Mild contrast boost + sharpening to lift faint screen-font text."""
    out = ImageEnhance.Contrast(gray).enhance(1.4)
    return out.filter(ImageFilter.SHARPEN)


def _ocr(img: Image.Image, psm: int) -> str:
    return pytesseract.image_to_string(
        img, lang="eng", config=f"{_BASE_CONFIG} --psm {psm}"
    )


def _merge_unique_lines(chunks) -> str:
    """Combine OCR chunks, dropping duplicate lines (case/space-insensitive)."""
    seen = set()
    out = []
    for chunk in chunks:
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            key = " ".join(stripped.lower().split())
            if key in seen:
                continue
            seen.add(key)
            out.append(stripped)
    return "\n".join(out)


def extract_text(image_path: str) -> str:
    """
    Open an image and extract all visible text via Tesseract OCR.

    Multi-pass strategy (robust to dark-mode UIs and scattered labels):
      1. Decide orientation from average brightness. Dark screenshots are
         inverted so light-on-dark text becomes dark-on-light for Tesseract.
      2. Primary orientation: a uniform-block pass (psm 6) for body text plus
         a sparse pass (psm 11) for scattered labels.
      3. Opposite orientation: one sparse pass (psm 11) to catch mixed-contrast
         elements (e.g. a dark button on a light page, or a light chart legend).
      4. Merge all passes and de-duplicate lines.

    Set the env var OCR_FAST=1 to use the original single-pass pipeline.
    Returns the extracted string (may be empty). Raises on failure.
    """
    gray = _to_grayscale(Image.open(image_path))

    if _FAST:
        return _ocr(_enhance(gray), psm=6).strip()

    mean_brightness = ImageStat.Stat(gray).mean[0]
    normal = _enhance(gray)
    inverted = _enhance(ImageOps.invert(gray))

    if mean_brightness < _DARK_THRESHOLD:
        primary, opposite = inverted, normal
    else:
        primary, opposite = normal, inverted

    passes = [
        _ocr(primary, psm=6),    # body text, primary orientation
        _ocr(primary, psm=11),   # scattered labels, primary orientation
        _ocr(opposite, psm=11),  # mixed-contrast elements, opposite orientation
    ]
    return _merge_unique_lines(passes).strip()
