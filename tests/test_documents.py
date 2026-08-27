from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from comfyui_py_workflow import documents
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
    with pytest.raises(DocumentReadError, match="blank or unreadable"):
        read_document(source)


def test_reads_image_only_pdf_with_offline_ocr(tmp_path: Path) -> None:
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=72)
    draw.text((60, 75), "OFFLINE STORY 2049", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    source = tmp_path / "scanned.pdf"
    document = fitz.open()
    page = document.new_page(width=700, height=130)
    page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(source)
    document.close()

    recognized = read_document(source).upper()
    assert "OFFLINE STORY" in recognized
    assert "2049" in recognized


def test_uses_ocr_when_pdf_text_layer_contains_control_garbage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "broken-map.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(
        documents,
        "_read_pdf",
        lambda path: '!"#$% E0 YC D8Y\x80\x81\x82\x83\x84\x85',
    )
    monkeypatch.setattr(
        documents,
        "_read_pdf_ocr",
        lambda path: "这是通过离线 OCR 恢复的正常故事。",
    )
    assert read_document(source) == "这是通过离线 OCR 恢复的正常故事。"


def test_keeps_healthy_pdf_text_layer_without_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "healthy.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(
        documents,
        "_read_pdf",
        lambda path: "第一幕，人物从咖啡馆走到公园。\n第二幕，他们在湖边交谈。",
    )

    def unexpected_ocr(path: Path) -> str:
        raise AssertionError("healthy text should not use OCR")

    monkeypatch.setattr(documents, "_read_pdf_ocr", unexpected_ocr)
    assert "咖啡馆" in read_document(source)
