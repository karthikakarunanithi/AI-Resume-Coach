import io

import docx
import pymupdf
import pytest

from app.services.text_extract import UnsupportedFileError, extract_text


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_pdf_text():
    assert "FastAPI" in extract_text(make_pdf("Skills: Python, FastAPI"))


def test_docx_text_includes_tables():
    text = extract_text(make_docx(["Karthika K", "Skills"], table=[["Python", "LangGraph"]]))
    assert "Karthika K" in text
    assert "Python | LangGraph" in text


def test_unsupported_file_rejected():
    with pytest.raises(UnsupportedFileError):
        extract_text(b"just some plain text")


def test_corrupt_pdf_rejected():
    with pytest.raises(UnsupportedFileError):
        extract_text(b"%PDF-1.7 garbage that is not a pdf")
