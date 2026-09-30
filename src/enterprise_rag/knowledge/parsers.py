import io
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from enterprise_rag.core.errors import KnowledgeValidationError
from enterprise_rag.knowledge.models import ParsedDocument

_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
_TEXT_EXTENSIONS = {".txt", ".text"}


class DocumentParser:
    """Parse supported source files into normalized text and metadata."""

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        extension = Path(filename).suffix.lower()
        if extension in _MARKDOWN_EXTENSIONS:
            return self._parse_markdown(content, filename)
        if extension in _TEXT_EXTENSIONS:
            return self._parse_text(content, filename)
        if extension == ".pdf":
            return self._parse_pdf(content, filename)
        raise KnowledgeValidationError(
            f"Unsupported file type: {extension or 'missing extension'}",
            status_code=415,
        )

    def _decode_text(self, content: bytes) -> str:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeValidationError("Text files must be UTF-8 encoded") from exc
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise KnowledgeValidationError("Document contains no readable text")
        return normalized

    def _parse_markdown(self, content: bytes, filename: str) -> ParsedDocument:
        text = self._decode_text(content)
        front_matter, body = self._extract_front_matter(text)
        heading = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
        title = heading.group(1).strip() if heading else Path(filename).stem
        return ParsedDocument(
            text=body,
            title=title,
            mime_type="text/markdown",
            metadata={"front_matter": front_matter} if front_matter else {},
        )

    def _parse_text(self, content: bytes, filename: str) -> ParsedDocument:
        return ParsedDocument(
            text=self._decode_text(content),
            title=Path(filename).stem,
            mime_type="text/plain",
        )

    def _parse_pdf(self, content: bytes, filename: str) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise KnowledgeValidationError("PDF could not be parsed") from exc
        text = "\n\n".join(page.strip() for page in pages if page.strip())
        if not text:
            raise KnowledgeValidationError(
                "PDF contains no extractable text; scanned PDFs require OCR"
            )
        pdf_metadata: dict[str, Any] = {}
        if reader.metadata:
            pdf_metadata = {
                str(key).lstrip("/"): str(value)
                for key, value in reader.metadata.items()
                if value is not None
            }
        return ParsedDocument(
            text=text,
            title=pdf_metadata.get("Title") or Path(filename).stem,
            mime_type="application/pdf",
            metadata={"page_count": len(reader.pages), "pdf": pdf_metadata},
        )

    def _extract_front_matter(self, text: str) -> tuple[dict[str, str], str]:
        if not text.startswith("---\n"):
            return {}, text
        closing = text.find("\n---\n", 4)
        if closing == -1:
            return {}, text
        raw_metadata = text[4:closing]
        metadata: dict[str, str] = {}
        for line in raw_metadata.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip():
                metadata[key.strip()] = value.strip().strip("\"'")
        return metadata, text[closing + 5 :].strip()
