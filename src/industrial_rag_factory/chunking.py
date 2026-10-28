"""Heading-aware sliding-window chunking. A deterministic token proxy, not model tokenizer."""
import hashlib
import re
from .contracts import Chunk, Document

TOKENS = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]")
HEAD = re.compile(r"^(#{1,6})\s+(.+)$")


def chunk_document(doc: Document, max_tokens: int = 220, overlap: int = 40) -> list[Chunk]:
    if max_tokens < 10 or overlap < 0 or overlap >= max_tokens:
        raise ValueError("Invalid max_tokens/overlap")
    sections: list[tuple[str, str]] = []
    headings: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer and "\n".join(buffer).strip():
            sections.append((" > ".join(headings) or "root", "\n".join(buffer).strip()))
        buffer.clear()

    for line in doc.text.splitlines():
        m = HEAD.match(line.strip())
        if m:
            flush()
            level = len(m.group(1))
            headings[:] = headings[:level-1]
            headings.append(m.group(2))
        else:
            buffer.append(line)
    flush()
    output = []
    for section, text in sections:
        tokens = TOKENS.findall(text)
        step = max_tokens - overlap
        for offset in range(0, len(tokens), step):
            window = tokens[offset:offset+max_tokens]
            if not window:
                break
            body = " ".join(window)
            cid = hashlib.sha256(
                f"{doc.document_id}:{section}:{offset}:{body}".encode()
            ).hexdigest()[:24]
            output.append(Chunk(cid, doc.document_id, len(output), section, body, len(window)))
            if offset + max_tokens >= len(tokens):
                break
    return output
