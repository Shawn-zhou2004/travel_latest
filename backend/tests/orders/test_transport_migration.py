import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260808_0027_transport_offers_and_mock_tickets.py"
)


def render_offline_sql(direction: str) -> str:
    spec = importlib.util.spec_from_file_location("transport_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(migration, direction)()
    return output.getvalue()


def test_transport_migration_upgrade_renders_mysql_sql() -> None:
    sql = render_offline_sql("upgrade")

    assert "DROP CHECK ck_travel_search_jobs_type" in sql
    assert "search_type IN ('train', 'flight', 'hotel', 'ride')" in sql
    assert "CREATE TABLE mock_transport_tickets" in sql
    assert "CONSTRAINT ck_mock_transport_tickets_type CHECK (transport_type IN ('train', 'flight'))" in sql


def test_transport_migration_downgrade_maps_train_before_constraint_narrowing() -> None:
    sql = render_offline_sql("downgrade")

    train_mapping = "UPDATE travel_search_jobs SET search_type = 'flight' WHERE search_type = 'train'"
    narrowed_constraint = "search_type IN ('flight', 'hotel', 'ride')"
    assert train_mapping in sql
    assert narrowed_constraint in sql
    assert sql.index(train_mapping) < sql.index(narrowed_constraint)
