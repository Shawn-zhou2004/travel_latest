from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.database import SessionLocal, engine
from app.core.settings import Settings
from app.modules.admin.models import OfficialKnowledgeSource
from app.modules.ai_rag.backfill import DomainBackfillService
from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.ingestion import KnowledgeIngestionService
from app.modules.ai_rag.types import KnowledgeDomain, RagResult
from app.modules.ai_workflows.runtime import open_domain_retrieval_runtime


async def _ensure_domain_stores() -> None:
    runtime = await open_domain_retrieval_runtime(Settings())
    await runtime.close()


async def _backfill_official_domain(*, apply: bool) -> tuple[int, int]:
    """Return selected and indexed document counts without mutating source records."""

    try:
        async with SessionLocal() as session:
            sources = list(
                (
                    await session.scalars(
                        select(OfficialKnowledgeSource)
                        .where(
                            OfficialKnowledgeSource.reviewed_at.is_not(None),
                            OfficialKnowledgeSource.status == "indexed",
                        )
                        .order_by(OfficialKnowledgeSource.id)
                    )
                ).all()
            )
        documents = DomainBackfillService().select_documents(official_sources=sources)
        if not apply:
            return len(documents), 0

        runtime = await open_domain_retrieval_runtime(Settings())
        try:
            milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.OFFICIAL]
            ingestion = KnowledgeIngestionService(runtime.embeddings, milvus, elasticsearch)
            for document in documents:
                await ingestion.ingest(document)
            return len(documents), len(documents)
        finally:
            await runtime.close()
    finally:
        await engine.dispose()


async def _verify_domain(
    *, domain: KnowledgeDomain, query: str, city_code: str | None, user_id: str | None
) -> RagResult:
    try:
        runtime = await open_domain_retrieval_runtime(Settings())
        try:
            return await runtime.catalog.retrieve(
                DomainRetrievalRequest(
                    domain=domain,
                    query=query,
                    city_code=city_code,
                    user_id=user_id,
                )
            )
        finally:
            await runtime.close()
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage fixed AI RAG domain stores.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ensure-domain-stores")
    backfill = subparsers.add_parser("backfill-domain")
    backfill.add_argument("--domain", choices=(KnowledgeDomain.OFFICIAL.value,), required=True)
    backfill.add_argument(
        "--apply",
        action="store_true",
        help="Write idempotent upserts after the default dry run.",
    )
    verify = subparsers.add_parser("verify-domain")
    verify.add_argument("--domain", choices=tuple(domain.value for domain in KnowledgeDomain), required=True)
    verify.add_argument("--query", required=True)
    verify.add_argument("--city-code")
    verify.add_argument("--user-id")
    args = parser.parse_args()
    if args.command == "ensure-domain-stores":
        asyncio.run(_ensure_domain_stores())
        return 0
    if args.command == "verify-domain":
        domain = KnowledgeDomain(args.domain)
        if domain is KnowledgeDomain.USER_MEMORY and not args.user_id:
            parser.error("--user-id is required when --domain user_memory")
        if domain is not KnowledgeDomain.USER_MEMORY and not args.city_code:
            parser.error("--city-code is required for public knowledge domains")
        if domain is not KnowledgeDomain.USER_MEMORY and args.user_id is not None:
            parser.error("--user-id is only allowed when --domain user_memory")
        result = asyncio.run(
            _verify_domain(
                domain=domain,
                query=args.query,
                city_code=args.city_code,
                user_id=args.user_id,
            )
        )
        document_ids = ",".join(item.citation.document_id for item in result.contexts)
        print(f"status={result.status.value}")
        print(f"context_count={len(result.contexts)}")
        print(f"domains={domain.value}")
        print(f"document_ids={document_ids}")
        return 0
    selected, indexed = asyncio.run(_backfill_official_domain(apply=args.apply))
    if args.apply:
        print(f"Indexed {indexed} official RAG documents from {selected} selected sources.")
    else:
        print(f"Dry run: {selected} official RAG documents would be indexed. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
