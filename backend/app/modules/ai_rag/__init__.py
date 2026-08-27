"""Module-local LangChain-compatible RAG boundary.

Application composition owns provider clients and configuration; this package owns
the knowledge document contract, ingestion flow, and retrieval semantics.
"""

from app.modules.ai_rag.ingestion import KnowledgeIngestionService
from app.modules.ai_rag.retrieval import RagRetrievalService
from app.modules.ai_rag.types import RagConfig

__all__ = ("KnowledgeIngestionService", "RagConfig", "RagRetrievalService")
