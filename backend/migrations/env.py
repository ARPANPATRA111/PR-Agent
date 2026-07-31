"""Alembic environment for the additive public-v2 schema."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.sqltypes import JSON

from config import settings
from public_models import PublicBase


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = settings.active_database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = PublicBase.metadata


def include_object(object_, name, type_, reflected, compare_to):
    # Legacy tables are preserved even though they are intentionally absent
    # from the public-v2 metadata.
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def compare_server_default(
    migration_context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    del (
        migration_context,
        inspected_column,
        inspected_default,
        metadata_default,
        rendered_metadata_default,
    )
    # PostgreSQL's JSON type has no equality operator, so Alembic's normal
    # default comparison raises for '{}' and '[]'. Defaults are fixed in the
    # reviewed migration; future JSON-default changes require an explicit
    # migration.
    if isinstance(metadata_column.type, JSON):
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=compare_server_default,
        include_object=include_object,
        render_as_batch=database_url.startswith("sqlite"),
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=compare_server_default,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
