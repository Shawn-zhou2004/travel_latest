from __future__ import annotations

import asyncio

import pytest

from app.modules.ai_rag import cli
from app.modules.ai_rag.types import (
    Citation,
    KnowledgeDomain,
    KnowledgeSourceType,
    RagContextItem,
    RagResult,
    RagStatus,
)


def test_ensure_domain_stores_closes_runtime(monkeypatch) -> None:
    class Runtime:
        closed = False

        async def close(self) -> None:
            self.closed = True

    runtime = Runtime()

    async def open_runtime(_settings):
        return runtime

    monkeypatch.setattr(cli, "open_domain_retrieval_runtime", open_runtime)
    asyncio.run(cli._ensure_domain_stores())
    assert runtime.closed is True


def test_domain_backfill_is_dry_run_by_default(monkeypatch, capsys) -> None:
    apply_values = []

    async def backfill(*, apply: bool) -> tuple[int, int]:
        apply_values.append(apply)
        return 2, 0

    monkeypatch.setattr(cli, "_backfill_official_domain", backfill)
    monkeypatch.setattr("sys.argv", ["ai-rag", "backfill-domain", "--domain", "official"])

    assert cli.main() == 0
    assert apply_values == [False]
    assert "Dry run" in capsys.readouterr().out


def test_domain_backfill_requires_apply_to_write(monkeypatch, capsys) -> None:
    apply_values = []

    async def backfill(*, apply: bool) -> tuple[int, int]:
        apply_values.append(apply)
        return 2, 2

    monkeypatch.setattr(cli, "_backfill_official_domain", backfill)
    monkeypatch.setattr("sys.argv", ["ai-rag", "backfill-domain", "--domain", "official", "--apply"])

    assert cli.main() == 0
    assert apply_values == [True]
    assert "Indexed 2 official" in capsys.readouterr().out


def test_verify_domain_prints_metadata_only_and_closes_resources(monkeypatch, capsys) -> None:
    class Catalog:
        request = None

        async def retrieve(self, request):
            self.request = request
            return RagResult(
                status=RagStatus.AVAILABLE,
                contexts=(
                    RagContextItem(
                        content="sensitive retrieved content",
                        citation=Citation(
                            document_id="official-1",
                            chunk_id="official-1:0",
                            source_type=KnowledgeSourceType.RULE,
                            source_id="rule-1",
                            city_code="330100",
                            poi_id=None,
                            source_updated_at=None,
                            knowledge_domain=KnowledgeDomain.OFFICIAL,
                        ),
                        score=0.9,
                    ),
                ),
            )

    class Runtime:
        closed = False
        catalog = Catalog()

        async def close(self) -> None:
            self.closed = True

    runtime = Runtime()
    async def open_runtime(_settings):
        return runtime

    class Engine:
        disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    engine = Engine()

    monkeypatch.setattr(cli, "open_domain_retrieval_runtime", open_runtime)
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-rag",
            "verify-domain",
            "--domain",
            "official",
            "--query",
            "museum hours",
            "--city-code",
            "330100",
        ],
    )

    assert cli.main() == 0
    assert runtime.catalog.request.domain is KnowledgeDomain.OFFICIAL
    assert runtime.catalog.request.user_id is None
    assert runtime.closed is True
    assert engine.disposed is True
    assert capsys.readouterr().out == (
        "status=available\n"
        "context_count=1\n"
        "domains=official\n"
        "document_ids=official-1\n"
    )


def test_verify_domain_requires_user_id_before_opening_runtime(monkeypatch) -> None:
    opened = False

    async def open_runtime(_settings):
        nonlocal opened
        opened = True
        raise AssertionError("runtime must not open for invalid arguments")

    monkeypatch.setattr(cli, "open_domain_retrieval_runtime", open_runtime)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-rag",
            "verify-domain",
            "--domain",
            "user_memory",
            "--query",
            "museum hours",
            "--city-code",
            "330100",
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert opened is False


def test_verify_domain_rejects_user_id_for_public_domains(monkeypatch) -> None:
    opened = False

    async def open_runtime(_settings):
        nonlocal opened
        opened = True
        raise AssertionError("runtime must not open for invalid arguments")

    monkeypatch.setattr(cli, "open_domain_retrieval_runtime", open_runtime)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-rag",
            "verify-domain",
            "--domain",
            "community",
            "--query",
            "museum hours",
            "--city-code",
            "330100",
            "--user-id",
            "user-1",
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert opened is False


def test_verify_private_domain_does_not_require_city_code(monkeypatch, capsys) -> None:
    class Catalog:
        request = None

        async def retrieve(self, request):
            self.request = request
            return RagResult(status=RagStatus.NO_RESULTS)

    class Runtime:
        catalog = Catalog()

        async def close(self) -> None:
            return None

    async def open_runtime(_settings):
        return Runtime()

    class Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(cli, "open_domain_retrieval_runtime", open_runtime)
    monkeypatch.setattr(cli, "engine", Engine())
    monkeypatch.setattr(
        "sys.argv",
        [
            "ai-rag",
            "verify-domain",
            "--domain",
            "user_memory",
            "--query",
            "vegetarian",
            "--user-id",
            "user-1",
        ],
    )

    assert cli.main() == 0
    assert Runtime.catalog.request.city_code is None
    assert capsys.readouterr().out.startswith("status=no_results\n")
