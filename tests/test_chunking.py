from enterprise_rag.knowledge.chunking import StructureAwareChunker
from enterprise_rag.knowledge.models import ParsedDocument


def test_markdown_chunking_preserves_heading_path_and_overlap() -> None:
    chunker = StructureAwareChunker(max_chars=200, overlap_chars=30)
    document = ParsedDocument(
        text="# 手册\n\n## 章节\n\n" + ("动力电池维护说明。" * 40),
        title="手册",
        mime_type="text/markdown",
    )

    chunks = chunker.chunk(document)

    assert len(chunks) > 1
    assert all(chunk.metadata["heading_path"] == "手册 > 章节" for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.content_hash and chunk.token_count > 0 for chunk in chunks)
