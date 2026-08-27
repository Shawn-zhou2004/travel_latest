from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256


class KnowledgeSourceType(StrEnum):
    COMMUNITY = "community"
    MEMORY = "memory"
    POI = "poi"
    RULE = "rule"
    TEMPLATE = "template"


class KnowledgeDomain(StrEnum):
    OFFICIAL = "official"
    COMMUNITY = "community"
    USER_MEMORY = "user_memory"


class AuthorityLevel(StrEnum):
    OFFICIAL = "official"
    COMMUNITY = "community"
    PRIVATE_MEMORY = "private_memory"


class RagStatus(StrEnum):
    AVAILABLE = "available"
    NO_RESULTS = "no_results"
    UNAVAILABLE = "unavailable"
    CLARIFICATION_REQUIRED = "clarification_required"


@dataclass(frozen=True)
class KnowledgeMetadata:
    """Metadata required on every indexed knowledge chunk."""

    document_id: str
    chunk_id: str
    source_type: KnowledgeSourceType
    source_id: str
    city_code: str | None
    poi_id: str | None
    language: str
    visibility: str
    status: str
    source_updated_at: datetime
    content_hash: str
    knowledge_domain: KnowledgeDomain | None = None
    authority_level: AuthorityLevel = AuthorityLevel.OFFICIAL
    reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    source_version: str = "1"
    supersedes_document_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        required = {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "language": self.language,
            "visibility": self.visibility,
            "status": self.status,
            "content_hash": self.content_hash,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Knowledge metadata fields are required: {', '.join(missing)}")
        if self.source_updated_at.tzinfo is None:
            raise ValueError("source_updated_at must be timezone-aware")
        if self.knowledge_domain is KnowledgeDomain.USER_MEMORY:
            if not self.user_id:
                raise ValueError("user_memory knowledge requires user_id")
            if self.visibility != "private":
                raise ValueError("user_memory knowledge must be private")
        elif self.user_id is not None:
            raise ValueError("public knowledge must not include user_id")


@dataclass(frozen=True)
class ReviewedKnowledgeDocument:
    """A source document that has passed the owning domain's review process."""

    document_id: str
    source_type: KnowledgeSourceType
    source_id: str
    text: str
    city_code: str | None
    poi_id: str | None
    language: str
    visibility: str
    status: str
    source_updated_at: datetime
    knowledge_domain: KnowledgeDomain | None = None
    authority_level: AuthorityLevel = AuthorityLevel.OFFICIAL
    reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    source_version: str = "1"
    supersedes_document_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        if self.status != "reviewed":
            raise ValueError("Only reviewed knowledge may enter the RAG index")
        if not self.text.strip():
            raise ValueError("Knowledge text is required")
        if self.knowledge_domain is KnowledgeDomain.USER_MEMORY:
            if not self.user_id or self.visibility != "private":
                raise ValueError("user_memory documents require user_id and private visibility")
        elif self.user_id is not None:
            raise ValueError("public knowledge documents must not include user_id")


@dataclass(frozen=True)
class KnowledgeChunk:
    page_content: str
    metadata: KnowledgeMetadata

    @classmethod
    def from_document(
        cls, document: ReviewedKnowledgeDocument, *, index: int, page_content: str
    ) -> "KnowledgeChunk":
        content_hash = sha256(page_content.encode("utf-8")).hexdigest()
        return cls(
            page_content=page_content,
            metadata=KnowledgeMetadata(
                document_id=document.document_id,
                chunk_id=f"{document.document_id}:{index}:{content_hash[:16]}",
                source_type=document.source_type,
                source_id=document.source_id,
                city_code=document.city_code,
                poi_id=document.poi_id,
                language=document.language,
                visibility=document.visibility,
                status=document.status,
                source_updated_at=document.source_updated_at.astimezone(UTC),
                content_hash=content_hash,
                knowledge_domain=document.knowledge_domain,
                authority_level=document.authority_level,
                reviewed_at=document.reviewed_at,
                next_review_at=document.next_review_at,
                source_version=document.source_version,
                supersedes_document_id=document.supersedes_document_id,
                user_id=document.user_id,
            ),
        )


@dataclass(frozen=True)
class RetrievalFilter:
    city_code: str | None
    visibility: str = "public"
    status: str = "reviewed"
    knowledge_domain: KnowledgeDomain | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        if self.knowledge_domain is KnowledgeDomain.USER_MEMORY:
            if not self.user_id:
                raise ValueError("user_memory retrieval requires user_id")
            if self.visibility != "private":
                raise ValueError("user_memory retrieval must be private")
        elif self.user_id is not None:
            raise ValueError("public retrieval must not include user_id")


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: KnowledgeChunk
    score: float
    source: str


@dataclass(frozen=True)
class Citation:
    document_id: str
    chunk_id: str
    source_type: KnowledgeSourceType
    source_id: str
    city_code: str | None
    poi_id: str | None
    source_updated_at: datetime
    knowledge_domain: KnowledgeDomain | None = None
    authority_level: AuthorityLevel = AuthorityLevel.OFFICIAL

    @classmethod
    def from_chunk(cls, chunk: KnowledgeChunk) -> "Citation":
        metadata = chunk.metadata
        return cls(
            document_id=metadata.document_id,
            chunk_id=metadata.chunk_id,
            source_type=metadata.source_type,
            source_id=metadata.source_id,
            city_code=metadata.city_code,
            poi_id=metadata.poi_id,
            source_updated_at=metadata.source_updated_at,
            knowledge_domain=metadata.knowledge_domain,
            authority_level=metadata.authority_level,
        )


@dataclass(frozen=True)
class RagContextItem:
    content: str
    citation: Citation
    score: float


@dataclass(frozen=True)
class RagResult:
    status: RagStatus
    contexts: tuple[RagContextItem, ...] = ()
    message: str | None = None


@dataclass(frozen=True)
class RagConfig:
    dense_top_k: int = 20
    bm25_top_k: int = 20
    final_top_k: int = 8
    min_score: float = 0.35
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if (self.dense_top_k, self.bm25_top_k, self.final_top_k, self.rrf_k) != (20, 20, 8, 60):
            raise ValueError("Phase-one RAG requires dense=20, bm25=20, final=8, and RRF k=60")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be between zero and one")


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    chunks_indexed: int
    content_hash: str
    indexed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
