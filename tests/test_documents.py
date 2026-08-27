from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from comfyui_py_workflow.documents import DocumentReadError, read_document


def test_reads_utf8_markdown(tmp_path: Path) -> None:
    source = tmp_path / "story.md"
    source.write_text("# 标题\n\n一个本地故事。\n", encoding="utf-8")
    assert read_document(source) == "# 标题\n\n一个本地故事。"


def test_reads_docx_text_without_office_dependency(tmp_path: Path) -> None:
    source = tmp_path / "story.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>第一幕</w:t></w:r></w:p>
    <w:p><w:r><w:t>人物走进雨中。</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    assert read_document(source) == "第一幕\n人物走进雨中。"


def test_rejects_unknown_document_type(tmp_path: Path) -> None:
    source = tmp_path / "story.rtf"
    source.write_text("story", encoding="utf-8")
    with pytest.raises(DocumentReadError, match="Unsupported input format"):
        read_document(source)


def test_reports_scanned_or_empty_pdf(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    source = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with source.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(DocumentReadError, match="Scanned PDFs require OCR"):
        read_document(source)
