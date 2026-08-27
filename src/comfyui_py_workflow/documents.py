from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


class DocumentReadError(RuntimeError):
    """Raised when a supported document cannot be converted to useful text."""


def read_document(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = source.read_text(encoding="utf-8-sig")
    elif suffix == ".docx":
        text = _read_docx(source)
    elif suffix == ".pdf":
        text = _read_pdf(source)
    else:
        raise DocumentReadError(
            f"Unsupported input format {suffix or '<none>'}; use TXT, MD, DOCX, or PDF"
        )
    text = _normalize(text)
    if not text:
        raise DocumentReadError(
            f"No readable text found in {source}. Scanned PDFs require OCR before planning."
        )
    return text


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise DocumentReadError(f"Cannot read DOCX file {path}: {exc}") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentReadError(f"DOCX contains invalid document XML: {path}") from exc
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        value = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        if value.strip():
            paragraphs.append(value.strip())
    return "\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentReadError(
            "PDF support requires the documents extra: python -m pip install -e '.[documents]'"
        ) from exc
    try:
        reader = PdfReader(path)
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except Exception as exc:
        raise DocumentReadError(f"Cannot extract text from PDF {path}: {exc}") from exc


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()
