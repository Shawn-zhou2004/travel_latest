from __future__ import with_statement

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import engine_from_config, pool

from app.models.base import Base
import app.modules.chat.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.ai_workflows.models  # noqa: F401
import app.modules.community.models  # noqa: F401
import app.modules.itineraries.models  # noqa: F401
import app.models.outbox  # noqa: F401
import app.models.user  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.orders.models  # noqa: F401
import app.modules.providers.models  # noqa: F401
import app.modules.search.models  # noqa: F401
import app.modules.media.models  # noqa: F401
import app.modules.exports.models  # noqa: F401
import app.modules.memberships.models  # noqa: F401
import app.modules.membership_purchases.models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

root_env = Path(__file__).parents[2] / ".env"
mysql_dsn = os.getenv("MYSQL_DSN") or dotenv_values(root_env).get("MYSQL_DSN")
if not mysql_dsn:
    raise RuntimeError(
        "MYSQL_DSN must be set in the environment or repository-root .env to run Alembic migrations"
    )
config.set_main_option("sqlalchemy.url", mysql_dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
