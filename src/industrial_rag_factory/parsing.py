"""Versioned PDF/DOCX/Markdown/TXT extraction. No OCR and no URL fetching in Stage 01."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from .contracts import Document

SUPPORTED = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def _pdf(data: bytes) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Install industrial-rag-factory[pdf]") from exc
    with fitz.open(stream=data, filetype="pdf") as pdf:
        return "\n\n".join(
            f"## Page {n}\n{page.get_text(sort=True)}"
            for n, page in enumerate(pdf, 1)
        )


def _docx(data: bytes) -> str:
    try:
        from docx import Document as Word
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        from docx.oxml.ns import qn
    except ImportError as exc:
        raise RuntimeError("Install industrial-rag-factory[docx]") from exc
    doc = Word(io.BytesIO(data))
    result = []
    for element in doc.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, doc)
            value = paragraph.text.strip()
            if value:
                style = paragraph.style.name if paragraph.style else ""
                match = re.match(r"Heading (\d+)", style)
                prefix = "#" * min(6, int(match.group(1))) + " " if match else ""
                result.append(prefix + value)
        elif element.tag == qn("w:tbl"):
            table = Table(element, doc)
            result += [" | ".join(c.text.replace("\n", " ") for c in row.cells)
                       for row in table.rows]
    return "\n\n".join(result)


def from_bytes(data: bytes, source_uri: str, suffix: str, *,
               revision: str = "1", tenant_id: str = "demo",
               access_groups: tuple[str, ...] = ("demo-readers",),
               title: str | None = None) -> Document:
    suffix = suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("Unsupported suffix: " + suffix)
    if not data or not source_uri or not tenant_id or not revision or not access_groups:
        raise ValueError("Source, revision, tenant, access groups and data are required")
    if suffix == ".pdf":
        text = _pdf(data)
    elif suffix == ".docx":
        text = _docx(data)
    else:
        text = data.decode("utf-8-sig")
    text = text.replace("\x00", "").replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("No extractable text; scanned documents require a later OCR stage")
    document_id = hashlib.sha256(
        f"{tenant_id}\x00{source_uri}\x00{revision}".encode()
    ).hexdigest()[:24]
    return Document(
        document_id=document_id, source_uri=source_uri, revision=revision,
        title=title or Path(source_uri).name or document_id,
        text=text, tenant_id=tenant_id, access_groups=tuple(access_groups),
        sha256=hashlib.sha256(data).hexdigest(), parser=suffix.lstrip("."),
    )


def from_path(path: str | Path, **kwargs: object) -> Document:
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Only files can be ingested")
    return from_bytes(path.read_bytes(), path.as_uri(), path.suffix, **kwargs)
