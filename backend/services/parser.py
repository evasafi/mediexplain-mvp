import pymupdf


def parse_pdf_text(file_path: str) -> str:
    """Return the text layer of every page, joined by newlines."""
    full_text = ""
    with pymupdf.open(file_path) as doc:
        for page in doc:
            text = page.get_text()
            if text:
                full_text += text + "\n"
    return full_text
