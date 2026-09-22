"""A migration é escrita à mão; os testes usam metadata.create_all().

Este teste é o que impede as duas de divergirem em silêncio.
"""

import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from kamnews.models import table_registry

ALEMBIC_INI = Path(__file__).resolve().parents[1] / 'alembic.ini'


def test_migration_matches_models(engine, monkeypatch):
    # env.py lê Settings().DATABASE_URL; a env var tem prioridade.
    monkeypatch.setitem(
        os.environ, 'DATABASE_URL', engine.url.render_as_string(False)
    )

    table_registry.metadata.drop_all(engine)

    config = Config(str(ALEMBIC_INI))
    config.set_main_option(
        'script_location', str(ALEMBIC_INI.parent / 'migrations')
    )

    try:
        command.upgrade(config, 'head')

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, table_registry.metadata)

        assert diff == [], f'Migration divergiu dos models: {diff}'
    finally:
        command.downgrade(config, 'base')
        # A tabela alembic_version não é dropada pelo downgrade.
        with engine.begin() as connection:
            connection.exec_driver_sql('DROP TABLE IF EXISTS alembic_version')
