import hashlib
import re
from dataclasses import dataclass
from typing import Any

from enterprise_rag.knowledge.models import ParsedDocument
from enterprise_rag.knowledge.text import approximate_token_count

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class RawChunk:
    ordinal: int
    content: str
    content_hash: str
    token_count: int
    metadata: dict[str, Any]


class StructureAwareChunker:
    def __init__(self, *, max_chars: int, overlap_chars: int) -> None:
        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, document: ParsedDocument) -> list[RawChunk]:
        sections = (
            self._markdown_sections(document.text)
            if document.mime_type == "text/markdown"
            else [(None, document.text)]
        )
        chunks: list[RawChunk] = []
        for heading_path, section_text in sections:
            for window in self._windows(section_text):
                content = window.strip()
                if not content:
                    continue
                metadata: dict[str, Any] = {}
                if heading_path:
                    metadata["heading_path"] = heading_path
                    content = f"{heading_path}\n\n{content}"
                chunks.append(
                    RawChunk(
                        ordinal=len(chunks),
                        content=content,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        token_count=approximate_token_count([content]),
                        metadata=metadata,
                    )
                )
        return chunks

    def _markdown_sections(self, text: str) -> list[tuple[str | None, str]]:
        headings: list[str] = []
        sections: list[tuple[str | None, str]] = []
        buffer: list[str] = []

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                sections.append((" > ".join(headings) or None, body))
            buffer.clear()

        for line in text.splitlines():
            match = _HEADING_PATTERN.match(line)
            if not match:
                buffer.append(line)
                continue
            flush()
            level = len(match.group(1))
            headings[level - 1 :] = [match.group(2).strip()]
        flush()
        return sections or [(None, text)]

    def _windows(self, text: str) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
        if len(normalized) <= self.max_chars:
            return [normalized]

        windows: list[str] = []
        start = 0
        while start < len(normalized):
            ideal_end = min(start + self.max_chars, len(normalized))
            end = ideal_end
            if ideal_end < len(normalized):
                boundary = max(
                    normalized.rfind("\n", start + self.max_chars // 2, ideal_end),
                    normalized.rfind("。", start + self.max_chars // 2, ideal_end),
                    normalized.rfind(". ", start + self.max_chars // 2, ideal_end),
                )
                if boundary > start:
                    end = boundary + 1
            windows.append(normalized[start:end].strip())
            if end >= len(normalized):
                break
            start = max(end - self.overlap_chars, start + 1)
        return windows
