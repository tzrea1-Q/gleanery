from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection, Engine

from gleanery.store.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided = config.attributes.get("connection")
    if isinstance(provided, Engine):
        with provided.connect() as connection:
            migrate(connection)
        return
    if provided is not None:
        migrate(provided)
        return
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()


def migrate(connection: Connection) -> None:
    in_transaction = connection.in_transaction()
    connection.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
    if not in_transaction:
        connection.commit()
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
