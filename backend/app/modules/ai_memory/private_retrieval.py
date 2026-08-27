from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import KnowledgeDomain, RagStatus


class PrivateMemoryGate(Protocol):
    async def filter_active_projected_memory_documents(
        self, user_id: str, document_versions: Mapping[str, str]
    ) -> set[str]: ...


class PrivateMemoryCatalog(Protocol):
    async def retrieve(self, request: DomainRetrievalRequest) -> Any: ...


class PrivateMemoryProfileLoader:
    """Loads only current, owner-scoped JSON profile documents from private RAG."""

    def __init__(self, gate: PrivateMemoryGate, catalog: PrivateMemoryCatalog) -> None:
        self._gate = gate
        self._catalog = catalog

    async def load_profile_memory(self, user_id: str) -> Mapping[str, object]:
        try:
            result = await self._catalog.retrieve(
                DomainRetrievalRequest(
                    domain=KnowledgeDomain.USER_MEMORY,
                    query="user profile preferences",
                    city_code=None,
                    user_id=user_id,
                )
            )
        except Exception:
            return {}
        if result.status is not RagStatus.AVAILABLE:
            return {}

        versions_by_document: dict[str, set[str]] = {}
        for item in result.contexts:
            source_version = getattr(item.citation, "source_version", None)
            if source_version is not None:
                versions_by_document.setdefault(str(item.citation.document_id), set()).add(
                    str(source_version)
                )
        document_versions = {
            document_id: next(iter(versions))
            for document_id, versions in versions_by_document.items()
            if len(versions) == 1
        }
        if not document_versions:
            return {}
        try:
            allowed_ids = await self._gate.filter_active_projected_memory_documents(
                user_id, document_versions
            )
        except Exception:
            return {}

        profile: dict[str, object] = {}
        for item in result.contexts:
            document_id = str(item.citation.document_id)
            if (
                document_id not in allowed_ids
                or getattr(item.citation, "source_version", None)
                != document_versions.get(document_id)
            ):
                continue
            document = _safe_profile_document(item.content)
            if document is not None:
                key, value = document
                profile[key] = value
        return profile


def _safe_profile_document(content: object) -> tuple[str, Mapping[str, object]] | None:
    if not isinstance(content, str):
        return None
    try:
        document = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(document, dict) or set(document) != {"key", "value"}:
        return None
    key = document["key"]
    value = document["value"]
    if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
        return None
    return key, value
