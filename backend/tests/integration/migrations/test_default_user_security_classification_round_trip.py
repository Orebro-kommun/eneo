"""Round trip for 202611201000: the organisation's default security level.

pytest -m migration_isolation \
    tests/integration/migrations/test_default_user_security_classification_round_trip.py
"""

from contextlib import closing
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202611190900"
_REVISION = "202611201000"
_COLUMN = "default_user_security_classification_id"


def _column_exists(cursor) -> bool:
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'tenants' AND column_name = %s)",
        (_COLUMN,),
    )
    return cursor.fetchone() == (True,)


def test_existing_tenant_gets_no_default_and_a_removed_level_empties_it():
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        config = expand._alembic_config(url)
        command.upgrade(config, _PREVIOUS_REVISION)
        tenant_id, level_id = str(uuid4()), str(uuid4())

        with closing(expand._connect(url)) as conn, conn.cursor() as cursor:
            conn.autocommit = True
            cursor.execute(
                "INSERT INTO tenants (id, name, quota_limit, provisioning, "
                "security_enabled, state) VALUES (%s, 'org', 1, false, true, 'active')",
                (tenant_id,),
            )
            cursor.execute(
                "INSERT INTO security_classifications "
                "(id, name, security_level, tenant_id) VALUES (%s, 'level', 0, %s)",
                (level_id, tenant_id),
            )

            command.upgrade(config, _REVISION)

            cursor.execute(f"SELECT {_COLUMN} FROM tenants WHERE id = %s", (tenant_id,))
            assert cursor.fetchone() == (None,)

            cursor.execute(
                f"UPDATE tenants SET {_COLUMN} = %s WHERE id = %s",
                (level_id, tenant_id),
            )
            cursor.execute(
                "DELETE FROM security_classifications WHERE id = %s", (level_id,)
            )
            cursor.execute(f"SELECT {_COLUMN} FROM tenants WHERE id = %s", (tenant_id,))
            assert cursor.fetchone() == (None,)

            command.downgrade(config, _PREVIOUS_REVISION)
            assert not _column_exists(cursor)

            command.upgrade(config, _REVISION)
            assert _column_exists(cursor)
