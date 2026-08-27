from __future__ import annotations

import re
from hashlib import sha256

from app.modules.ai_rag.protocols import EmbeddingProvider, ElasticsearchBm25Store, MilvusDenseStore
from app.modules.ai_rag.types import IngestionResult, KnowledgeChunk, ReviewedKnowledgeDocument


class KnowledgeIngestionService:
    """Indexes one reviewed source into both retrieval projections.

    Chunking strategy: recursive separator-aware splitting. Text is first split by
    paragraphs, then sentences, then clauses; only a piece with no separator at all
    is hard-cut. Consecutive chunks overlap so information spanning a boundary stays
    retrievable in both chunks.
    """

    _PARAGRAPH_SEPARATORS = ("\n\n", "\n")
    _SENTENCE_SEPARATORS = ("。", "！", "？", "!", "?", "…", "；", ";")
    _CLAUSE_SEPARATORS = ("，", ",", "、", "：", ":")

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        milvus: MilvusDenseStore,
        elasticsearch: ElasticsearchBm25Store,
        *,
        chunk_size: int = 800,
        chunk_overlap: int | None = None,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap is None:
            chunk_overlap = chunk_size // 8
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")
        self.embeddings = embeddings
        self.milvus = milvus
        self.elasticsearch = elasticsearch
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def ingest(self, document: ReviewedKnowledgeDocument) -> IngestionResult:
        chunks = self._chunk(document)
        vectors = await self.embeddings.embed_documents([chunk.page_content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedding provider returned a vector count that does not match chunks")
        await self.milvus.upsert(chunks, vectors)
        await self.elasticsearch.index(chunks)
        return IngestionResult(
            document_id=document.document_id,
            chunks_indexed=len(chunks),
            content_hash=sha256(document.text.encode("utf-8")).hexdigest(),
        )

    def _chunk(self, document: ReviewedKnowledgeDocument) -> list[KnowledgeChunk]:
        text = document.text.strip()
        if not text:
            return []
        pieces = self._split_pieces(text)
        chunks = self._assemble_chunks(pieces)
        return [
            KnowledgeChunk.from_document(document, index=index, page_content=content)
            for index, content in enumerate(chunks)
        ]

    def _split_pieces(self, text: str) -> list[str]:
        """Recursively split text into pieces no larger than chunk_size."""
        if len(text) <= self.chunk_size:
            return [text]
        for separators in (self._PARAGRAPH_SEPARATORS, self._SENTENCE_SEPARATORS, self._CLAUSE_SEPARATORS):
            pieces = self._split_by(text, separators)
            if len(pieces) > 1:
                result: list[str] = []
                for piece in pieces:
                    result.extend(self._split_pieces(piece))
                return result
        # No separator produced a split: hard cut as the last resort.
        return [text[start : start + self.chunk_size] for start in range(0, len(text), self.chunk_size)]

    def _split_by(self, text: str, separators: tuple[str, ...]) -> list[str]:
        """Split text so that each separator stays attached to the piece before it."""
        pattern = "|".join(re.escape(separator) for separator in separators)
        parts = re.split(f"({pattern})", text)
        pieces: list[str] = []
        current = ""
        for part in parts:
            current += part
            if re.fullmatch(pattern, part):
                if current.strip():
                    pieces.append(current)
                current = ""
        if current.strip():
            pieces.append(current)
        return pieces

    def _assemble_chunks(self, pieces: list[str]) -> list[str]:
        """Greedy-merge pieces up to chunk_size, prepending an overlap tail."""
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            if not current:
                current = piece
            elif len(current) + len(piece) <= self.chunk_size:
                current += piece
            else:
                chunks.append(current)
                tail = self._overlap_tail(current)
                current = tail + piece if tail else piece
        if current:
            chunks.append(current)
        return chunks

    def _overlap_tail(self, text: str) -> str:
        """Trailing portion of text up to chunk_overlap chars, aligned to a sentence start."""
        budget = min(self.chunk_overlap, len(text))
        if budget <= 0:
            return ""
        tail = text[-budget:]
        match = re.search(r"[。！？!?…；;\n]", tail)
        if match:
            tail = tail[match.end() :]
        return tail
