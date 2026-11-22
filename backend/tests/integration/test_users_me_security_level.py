"""GET /api/v1/users/me/ says which level the user works at and where it comes from."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


async def _set_default(db_container, tenant_id, *, security_enabled: bool):
    async with db_container() as container:
        session = container.session()
        row = SecurityClassification(
            name=f"level-{uuid4().hex[:6]}", security_level=0, tenant_id=tenant_id
        )
        session.add(row)
        await session.flush()
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                security_enabled=security_enabled,
                default_user_security_classification_id=row.id,
            )
        )
        return row.id


async def _level_of_me(client, headers) -> dict:
    response = await client.get("/api/v1/users/me/", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["effective_security_level"]


async def test_user_has_no_level_when_none_is_set(client, admin_headers):
    assert await _level_of_me(client, admin_headers) == {
        "security_classification_id": None,
        "source": "none",
        "user_group_id": None,
    }


async def test_user_works_at_the_organisations_default(
    client, admin_headers, db_container, admin_user
):
    default_id = await _set_default(
        db_container, admin_user.tenant_id, security_enabled=True
    )

    assert await _level_of_me(client, admin_headers) == {
        "security_classification_id": str(default_id),
        "source": "default",
        "user_group_id": None,
    }


async def test_user_has_no_level_while_classification_is_disabled(
    client, admin_headers, db_container, admin_user
):
    await _set_default(db_container, admin_user.tenant_id, security_enabled=False)

    assert (await _level_of_me(client, admin_headers))["source"] == "none"
