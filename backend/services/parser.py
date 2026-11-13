"""Turn an uploaded file into text.

- The file type is decided by its signature (magic bytes), never by the
  file name or the browser's content type.
- PDF pages with a text layer are read directly.
- Images (PNG, JPG) and PDF pages without a text layer (scans) are read
  with OCR: PyMuPDF's built-in Tesseract engine plus Tesseract's English
  language data. See `find_tessdata` for where that data is looked up.
"""
import logging
import os
import shutil
from dataclasses import dataclass

import pymupdf

logger = logging.getLogger(__name__)

SIGNATURES = (
    ("pdf", b"%PDF-"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpg", b"\xff\xd8\xff"),
)
OCR_LANGUAGE = "eng"
OCR_DPI = 300
MAX_OCR_PAGES = 10
# A page with fewer characters than this in its text layer is treated as a scan.
MIN_TEXT_CHARS = 20
# Refuse absurd images before OCR (decompression bombs, giant scans).
MAX_IMAGE_PIXELS = 40_000_000

_WINDOWS_TESSDATA = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
)


class UnsupportedFileError(Exception):
    """Not a PDF, PNG or JPG by signature."""


class UnreadableFileError(Exception):
    """Has the right signature but cannot be opened, or is too large to OCR."""


class OcrUnavailableError(Exception):
    """OCR is needed but Tesseract language data is not installed."""


@dataclass
class ExtractedText:
    text: str
    kind: str          # "pdf", "png" or "jpg"
    ocr_used: bool     # True if any text came from OCR


def detect_kind(data: bytes) -> str:
    for kind, magic in SIGNATURES:
        if data.startswith(magic):
            return kind
    raise UnsupportedFileError("Not a PDF, PNG or JPG file.")


def find_tessdata() -> str | None:
    """Tesseract language data folder, or None if OCR is not set up.

    Order: TESSDATA_PREFIX, `tesseract` on PATH, default Windows install folders.
    """
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        return env if os.path.isdir(env) else None
    exe = shutil.which("tesseract")
    if exe:
        candidate = os.path.join(os.path.dirname(exe), "tessdata")
        if os.path.isdir(candidate):
            return candidate
        try:
            return pymupdf.get_tessdata()
        except Exception:
            pass
    for folder in _WINDOWS_TESSDATA:
        if os.path.isfile(os.path.join(folder, f"{OCR_LANGUAGE}.traineddata")):
            return folder
    return None


def ocr_available() -> bool:
    folder = find_tessdata()
    return bool(folder) and os.path.isfile(os.path.join(folder, f"{OCR_LANGUAGE}.traineddata"))


def _ocr_page(page, tessdata: str) -> str:
    tp = page.get_textpage_ocr(language=OCR_LANGUAGE, dpi=OCR_DPI, full=True, tessdata=tessdata)
    # sort=True gives reading order (top to bottom, left to right), which keeps table rows together.
    return page.get_text(textpage=tp, sort=True)


def image_size(data: bytes, kind: str) -> tuple[int, int]:
    """Width and height from the PNG or JPEG header, without decoding the image."""
    if kind == "png":
        # IHDR is always the first chunk: 8-byte signature, 4 length, 4 "IHDR", then w, h.
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise UnreadableFileError("PNG header is damaged.")
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if kind == "jpg":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                raise UnreadableFileError("JPEG header is damaged.")
            marker = data[i + 1]
            if marker == 0xFF:  # padding
                i += 1
                continue
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            # Start-of-frame markers carry the size: C0-CF except C4, C8, CC.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return w, h
            i += 2 + seg_len
        raise UnreadableFileError("JPEG size not found.")
    raise ValueError(kind)


def _open(file_path: str, kind: str):
    # Read into memory and open from bytes. Opening by path lets PyMuPDF keep a
    # handle on the temp file after a failed open, and on Windows that blocks
    # the router from deleting the upload.
    with open(file_path, "rb") as f:
        data = f.read()
    if kind != "pdf":
        w, h = image_size(data, kind)
        if w == 0 or h == 0:
            raise UnreadableFileError("Image has no size.")
        if w * h > MAX_IMAGE_PIXELS:
            raise UnreadableFileError(f"Image too large to read ({w}x{h}).")
    try:
        doc = pymupdf.open(stream=data, filetype=kind)
        if kind != "pdf":
            # An image opens as a one-page document. Convert it to a PDF page so
            # text extraction and OCR work the same way for every upload.
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            doc = pymupdf.open("pdf", pdf_bytes)
    except Exception as e:
        raise UnreadableFileError(f"Could not open {kind}: {type(e).__name__}") from e
    return doc


def extract_text(file_path: str, kind: str) -> ExtractedText:
    """Text from a PDF or image, using OCR where there is no text layer."""
    doc = _open(file_path, kind)
    parts: list[str] = []
    ocr_used = False
    tessdata = None
    ocr_pages = 0
    try:
        if doc.page_count == 0:
            raise UnreadableFileError("Document has no pages.")
        for page in doc:
            text = page.get_text()
            if len(text.strip()) >= MIN_TEXT_CHARS:
                parts.append(text)
                continue
            # No usable text layer: this page is a scan or a photo.
            if ocr_pages >= MAX_OCR_PAGES:
                logger.warning("OCR page limit (%d) reached; skipping remaining pages", MAX_OCR_PAGES)
                break
            if tessdata is None:
                tessdata = find_tessdata()
                if not tessdata:
                    raise OcrUnavailableError(
                        "OCR needed but Tesseract language data was not found. "
                        "Install Tesseract or set TESSDATA_PREFIX."
                    )
            parts.append(_ocr_page(page, tessdata))
            ocr_pages += 1
            ocr_used = True
    finally:
        doc.close()
    text = "\n".join(p for p in parts if p.strip())
    if ocr_used:
        logger.info("OCR used on %d page(s) of a %s upload", ocr_pages, kind)
    return ExtractedText(text=text, kind=kind, ocr_used=ocr_used)


def parse_pdf_text(file_path: str) -> str:
    """Text layer of a PDF only (no OCR). Kept for scripts and tests."""
    full_text = ""
    with pymupdf.open(file_path) as doc:
        for page in doc:
            text = page.get_text()
            if text:
                full_text += text + "\n"
    return full_text
