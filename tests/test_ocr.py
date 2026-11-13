"""File-signature validation and OCR for images and scanned PDFs.

OCR itself is mocked in most tests. `test_real_ocr_*` run only when
Tesseract language data is installed, and are skipped otherwise.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import reports
from backend.services import parser
from backend.services.parser import (
    OcrUnavailableError, UnreadableFileError, UnsupportedFileError,
    detect_kind, extract_text, image_size,
)
from tests.conftest import make_pdf

ROOT = Path(__file__).resolve().parents[1]
PNG = (ROOT / "sample_cbc.png").read_bytes()
JPG = (ROOT / "sample_cbc.jpg").read_bytes()
SCAN = (ROOT / "sample_scanned.pdf").read_bytes()
TEXT_PDF = (ROOT / "sample_cbc.pdf").read_bytes()

OCR_TEXT = (
    "COMPLETE BLOOD COUNT\nHemoglobin 10.2 g/dL 12.0 - 15.5 L\n"
    "WBC 7.1 x10^3/uL 4.0 - 11.0\nPlatelets 450 x10^3/uL 150 - 400 H\n"
)


@pytest.fixture
def fake_ocr(monkeypatch):
    calls = []

    def ocr(page, tessdata):
        calls.append(tessdata)
        return OCR_TEXT

    monkeypatch.setattr(parser, "find_tessdata", lambda: "fake-tessdata")
    monkeypatch.setattr(parser, "_ocr_page", ocr)
    return calls


@pytest.fixture
def no_ocr(monkeypatch):
    monkeypatch.setattr(parser, "find_tessdata", lambda: None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(reports, "generate_explanation",
                        lambda text: {"markers": [], "seen_text": text})
    return TestClient(app, raise_server_exceptions=False), tmp_path


def post(client, data, name, ctype="application/octet-stream"):
    return client.post("/reports/upload", files={"file": (name, data, ctype)})


# --- signature detection --------------------------------------------------------

@pytest.mark.parametrize("data,kind", [
    (TEXT_PDF, "pdf"), (PNG, "png"), (JPG, "jpg"), (SCAN, "pdf"),
])
def test_detect_kind(data, kind):
    assert detect_kind(data) == kind


@pytest.mark.parametrize("data", [
    b"", b"%PDF", b"hello.pdf", b"GIF89a....", b"PK\x03\x04zip", b"\xff\xd8", b"<svg></svg>",
    b"\x89PNX\r\n\x1a\n",
])
def test_detect_kind_rejects_other_files(data):
    with pytest.raises(UnsupportedFileError):
        detect_kind(data)


def test_image_size_from_headers():
    assert image_size(PNG, "png") == image_size(JPG, "jpg")
    w, h = image_size(PNG, "png")
    assert w > 1000 and h > 1000


def test_image_size_rejects_damaged_headers():
    with pytest.raises(UnreadableFileError):
        image_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "png")
    with pytest.raises(UnreadableFileError):
        image_size(b"\xff\xd8\xff" + b"\x00" * 20, "jpg")


# --- extraction -------------------------------------------------------------------

def write(tmp_path, data, kind):
    p = tmp_path / f"upload.{kind}"
    p.write_bytes(data)
    return str(p)


def test_text_pdf_does_not_use_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "_ocr_page", lambda *a: pytest.fail("OCR should not run"))
    out = extract_text(write(tmp_path, TEXT_PDF, "pdf"), "pdf")
    assert out.ocr_used is False
    assert "Hemoglobin" in out.text


@pytest.mark.parametrize("data,kind", [(PNG, "png"), (JPG, "jpg"), (SCAN, "pdf")])
def test_images_and_scans_use_ocr(tmp_path, fake_ocr, data, kind):
    out = extract_text(write(tmp_path, data, kind), kind)
    assert out.ocr_used is True
    assert "Hemoglobin 10.2" in out.text
    assert fake_ocr == ["fake-tessdata"]


def test_ocr_unavailable_raises(tmp_path, no_ocr):
    with pytest.raises(OcrUnavailableError):
        extract_text(write(tmp_path, PNG, "png"), "png")


def test_oversized_image_is_refused_before_decoding(tmp_path, fake_ocr, monkeypatch):
    monkeypatch.setattr(parser, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(UnreadableFileError):
        extract_text(write(tmp_path, PNG, "png"), "png")
    assert fake_ocr == []


def test_ocr_page_limit(tmp_path, fake_ocr, monkeypatch):
    monkeypatch.setattr(parser, "MAX_OCR_PAGES", 2)
    import pymupdf
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page()
    data = doc.tobytes()
    extract_text(write(tmp_path, data, "pdf"), "pdf")
    assert len(fake_ocr) == 2


# --- through the API ------------------------------------------------------------------

@pytest.mark.parametrize("data,name", [
    (PNG, "report.png"), (JPG, "report.jpg"), (SCAN, "scan.pdf"),
])
def test_api_accepts_images_and_scans(client, fake_ocr, data, name):
    c, upload_dir = client
    r = post(c, data, name)
    assert r.status_code == 200
    body = r.json()
    assert body["ocr_used"] is True
    assert "Hemoglobin 10.2" in body["seen_text"]
    assert list(upload_dir.iterdir()) == []


def test_api_trusts_signature_not_extension(client, fake_ocr):
    c, _ = client
    # A PNG named .pdf with a PDF content type is still handled as a PNG.
    r = post(c, PNG, "report.pdf", "application/pdf")
    assert r.status_code == 200 and r.json()["ocr_used"] is True
    # A text file named .png is rejected.
    r = post(c, b"just some text", "report.png", "image/png")
    assert r.status_code == 400


def test_api_damaged_image_is_400_not_500(client, fake_ocr):
    c, upload_dir = client
    r = post(c, b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "broken.png")
    assert r.status_code == 400
    assert list(upload_dir.iterdir()) == []


def test_api_damaged_pdf_is_400_not_500(client):
    c, _ = client
    r = post(c, b"%PDF-1.7\nthis is not really a pdf", "broken.pdf")
    assert r.status_code == 400


def test_api_ocr_unavailable_is_501(client, no_ocr):
    c, upload_dir = client
    r = post(c, PNG, "report.png")
    assert r.status_code == 501
    assert list(upload_dir.iterdir()) == []


def test_api_text_pdf_reports_no_ocr(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(parser, "_ocr_page", lambda *a: pytest.fail("OCR should not run"))
    r = post(c, make_pdf("Hemoglobin 10.2 g/dL 12.0 - 15.5"), "r.pdf")
    assert r.status_code == 200 and r.json()["ocr_used"] is False


def test_health_reports_ocr_status(client, no_ocr):
    c, _ = client
    assert c.get("/health").json()["ocr_available"] is False


# --- real OCR (only when Tesseract is installed) -----------------------------------

needs_tesseract = pytest.mark.skipif(
    not parser.ocr_available(), reason="Tesseract language data not installed"
)


ALL_VALUES = ("Hemoglobin", "10.2", "7.1", "450", "78", "12.0", "15.5", "150", "400")


@needs_tesseract
@pytest.mark.parametrize("data,kind", [(PNG, "png"), (SCAN, "pdf")])
def test_real_ocr_reads_sample_values(tmp_path, data, kind):
    out = extract_text(write(tmp_path, data, kind), kind)
    assert out.ocr_used is True
    for expected in ALL_VALUES:
        assert expected in out.text, f"{expected!r} missing from OCR text:\n{out.text}"


@needs_tesseract
def test_real_ocr_jpg_misread_is_caught_by_verification(tmp_path):
    """JPEG artifacts make Tesseract misread small digits: in this sample WBC
    "7.1" comes out as something like "Peo,". OCR is not tuned to hide that.
    What matters is that verification flags the marker instead of trusting it."""
    from backend.services.verifier import verify_markers

    out = extract_text(write(tmp_path, JPG, "jpg"), "jpg")
    assert out.ocr_used is True
    for expected in ("Hemoglobin", "10.2", "450", "78", "12.0", "15.5"):
        assert expected in out.text, f"{expected!r} missing from OCR text:\n{out.text}"

    wbc = {"name": "WBC", "value": "7.1", "unit": "x10^3/uL", "reference_range": "4.0 - 11.0",
           "status": "normal", "explanation": "e"}
    hb = {"name": "Hemoglobin", "value": "10.2", "unit": "g/dL", "reference_range": "12.0 - 15.5",
          "status": "low", "explanation": "e"}
    checked, warnings = verify_markers([hb, wbc], out.text)
    assert checked[0]["verified"] is True
    if "7.1" not in out.text:  # the misread happened, as it does with this sample
        assert checked[1]["verified"] is False
        assert any("7.1" in w for w in warnings)
