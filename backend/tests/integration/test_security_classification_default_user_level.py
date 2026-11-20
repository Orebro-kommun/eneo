"""The organisation's default level: PUT /api/v1/security-classifications/default-user-level/."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

URL = "/api/v1/security-classifications/default-user-level/"
LIST_URL = "/api/v1/security-classifications/"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def non_admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"non-admin-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"non-admin-{uuid4().hex[:8]}@example.com",
                username=f"non_admin_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def classification_id(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        row = SecurityClassification(
            name=f"internal-{uuid4().hex[:8]}",
            security_level=0,
            tenant_id=admin_user.tenant_id,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _stored_default(db_container, tenant_id):
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Tenants.default_user_security_classification_id).where(
                Tenants.id == tenant_id
            )
        )


async def test_no_default_level_is_listed_until_one_is_set(client, admin_headers):
    listed = await client.get(LIST_URL, headers=admin_headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["default_user_security_classification_id"] is None


async def test_default_level_is_listed_once_set_and_gone_once_cleared(
    client, admin_headers, classification_id
):
    set_response = await client.put(
        URL,
        headers=admin_headers,
        json={"security_classification": {"id": str(classification_id)}},
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json() == {
        "default_user_security_classification_id": str(classification_id)
    }
    listed = await client.get(LIST_URL, headers=admin_headers)
    assert listed.json()["default_user_security_classification_id"] == str(
        classification_id
    )

    cleared = await client.put(
        URL, headers=admin_headers, json={"security_classification": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"default_user_security_classification_id": None}
    listed = await client.get(LIST_URL, headers=admin_headers)
    assert listed.json()["default_user_security_classification_id"] is None


async def test_default_level_must_be_an_existing_classification(client, admin_headers):
    response = await client.put(
        URL,
        headers=admin_headers,
        json={"security_classification": {"id": str(uuid4())}},
    )

    assert response.status_code == 404, response.text


async def test_non_admin_cannot_set_the_default_level(
    client, non_admin_headers, classification_id, db_container, admin_user
):
    response = await client.put(
        URL,
        headers=non_admin_headers,
        json={"security_classification": {"id": str(classification_id)}},
    )

    assert response.status_code == 403, response.text
    assert await _stored_default(db_container, admin_user.tenant_id) is None


async def test_classification_that_is_the_default_cannot_be_deleted_by_mistake(
    client, admin_headers, classification_id, db_container, admin_user
):
    await client.put(
        URL,
        headers=admin_headers,
        json={"security_classification": {"id": str(classification_id)}},
    )

    response = await client.delete(
        f"{LIST_URL}{classification_id}/", headers=admin_headers
    )

    assert response.status_code == 400, response.text
    assert "default_user_level" in response.text
    assert await _stored_default(db_container, admin_user.tenant_id) == (
        classification_id
    )


async def test_forced_delete_of_the_default_clears_it(
    client, admin_headers, classification_id, db_container, admin_user
):
    await client.put(
        URL,
        headers=admin_headers,
        json={"security_classification": {"id": str(classification_id)}},
    )

    response = await client.delete(
        f"{LIST_URL}{classification_id}/?force=true", headers=admin_headers
    )

    assert response.status_code == 204, response.text
    assert await _stored_default(db_container, admin_user.tenant_id) is None
