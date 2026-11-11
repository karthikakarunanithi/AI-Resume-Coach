import io
import re

import docx
import pymupdf

PDF = "pdf"
DOCX = "docx"


class UnsupportedFileError(ValueError):
    pass


def detect_file_type(data: bytes) -> str:
    """Sniff magic bytes rather than trusting the filename or client-sent content type."""
    if data.startswith(b"%PDF"):
        return PDF
    if data.startswith(b"PK\x03\x04"):  # DOCX is a zip archive
        return DOCX
    raise UnsupportedFileError("Only PDF and DOCX files are supported")


def extract_text(data: bytes) -> str:
    kind = detect_file_type(data)
    try:
        text = _pdf_text(data) if kind == PDF else _docx_text(data)
    except Exception as e:  # corrupt files raise many library-specific errors
        raise UnsupportedFileError(f"Could not read {kind.upper()} file") from e
    return _normalize(text)


def _pdf_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    # Many resume templates put content in tables
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _normalize(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()
