from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
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
        if not _looks_readable_pdf_text(text):
            text = _read_pdf_ocr(source)
    else:
        raise DocumentReadError(
            f"Unsupported input format {suffix or '<none>'}; use TXT, MD, DOCX, or PDF"
        )
    text = _normalize(text)
    if not text:
        raise DocumentReadError(
            f"No readable text found in {source}. The PDF may be blank or unreadable."
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


def _looks_readable_pdf_text(text: str) -> bool:
    """Reject broken font maps that technically produce non-empty PDF text."""
    normalized = _normalize(text)
    visible = [character for character in normalized if not character.isspace()]
    if not visible:
        return False

    invalid = sum(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"}
        or character == "\ufffd"
        for character in visible
    )
    if invalid / len(visible) > 0.005:
        return False

    wordlike = sum(character.isalnum() for character in visible)
    if wordlike / len(visible) < 0.25:
        return False
    return True


def _read_pdf_ocr(path: Path) -> str:
    try:
        import pymupdf
    except ImportError as exc:
        raise DocumentReadError(
            "This appears to be a scanned PDF. Offline OCR requires PyMuPDF plus "
            "RapidOCR, or PyMuPDF plus a local Tesseract executable."
        ) from exc

    rapidocr = None
    try:
        import rapidocr as rapidocr_package
        from rapidocr import RapidOCR

        model_dir = Path(rapidocr_package.__file__).resolve().parent / "models"
        required_models = (
            "PP-OCRv6_det_small.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "PP-OCRv6_rec_small.onnx",
        )
        missing_models = [name for name in required_models if not (model_dir / name).is_file()]
        if not missing_models:
            rapidocr = RapidOCR()
    except ImportError:
        pass
    tesseract = shutil.which("tesseract")
    if rapidocr is None and tesseract is None:
        raise DocumentReadError(
            "This appears to be a scanned PDF, but no offline OCR backend is installed. "
            "Install the project's ocr extra before disconnecting from the internet."
        )

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise DocumentReadError(f"Cannot open scanned PDF {path}: {exc}") from exc

    pages: list[str] = []
    try:
        for page in document:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            if rapidocr is not None:
                try:
                    import numpy
                except ImportError as exc:
                    raise DocumentReadError("RapidOCR requires NumPy") from exc
                image = numpy.frombuffer(pixmap.samples, dtype=numpy.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                result = rapidocr(image)
                lines = [str(value).strip() for value in (result.txts or []) if value]
                pages.append("\n".join(lines))
                continue

            with tempfile.TemporaryDirectory(prefix="cpw-ocr-") as temporary:
                image_path = Path(temporary) / "page.png"
                pixmap.save(image_path)
                completed = subprocess.run(
                    [str(tesseract), str(image_path), "stdout", "-l", "chi_sim+eng"],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if completed.returncode != 0:
                    raise DocumentReadError(
                        f"Tesseract OCR failed on page {page.number + 1}: {completed.stderr.strip()}"
                    )
                pages.append(completed.stdout.strip())
    finally:
        document.close()
    return "\n\n".join(pages)


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()
