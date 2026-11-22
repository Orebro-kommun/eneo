"""Shared spaces below the default user level:
GET /api/v1/security-classifications/spaces-below-default/."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

URL = "/api/v1/security-classifications/spaces-below-default/"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def levels(db_container, admin_user) -> dict[str, UUID]:
    async with db_container() as container:
        session = container.session()
        ids = {}
        for name, level in (("low", 1), ("high", 2)):
            row = SecurityClassification(
                name=f"{name}-{uuid4().hex[:6]}",
                security_level=level,
                tenant_id=admin_user.tenant_id,
            )
            session.add(row)
            await session.flush()
            ids[name] = row.id
        return ids


async def _shared_space(client, headers, db_container, level: UUID | None) -> str:
    created = await client.post(
        "/api/v1/spaces/", headers=headers, json={"name": f"s-{uuid4().hex[:6]}"}
    )
    assert created.status_code == 201, created.text
    async with db_container() as container:
        await container.session().execute(
            sa.update(Spaces)
            .where(Spaces.id == UUID(created.json()["id"]))
            .values(security_classification_id=level)
        )
    return created.json()["id"]


async def _set_default(db_container, tenant_id, level: UUID | None) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                security_enabled=True, default_user_security_classification_id=level
            )
        )


async def test_it_lists_the_shared_spaces_below_the_default_level(
    client, admin_headers, db_container, admin_user, levels
):
    unclassified = await _shared_space(client, admin_headers, db_container, None)
    below = await _shared_space(client, admin_headers, db_container, levels["low"])
    at_level = await _shared_space(client, admin_headers, db_container, levels["high"])
    personal = await client.get("/api/v1/spaces/type/personal/", headers=admin_headers)
    await _set_default(db_container, admin_user.tenant_id, levels["high"])

    response = await client.get(URL, headers=admin_headers)

    assert response.status_code == 200, response.text
    listed = {item["id"]: item for item in response.json()["items"]}
    assert {unclassified, below} <= listed.keys()
    assert at_level not in listed
    assert personal.json()["id"] not in listed
    assert listed[below] == {
        "id": below,
        "name": listed[below]["name"],
        "security_classification_id": str(levels["low"]),
    }
    assert listed[unclassified]["security_classification_id"] is None
    # The organisation's own space is not a shared space.
    async with db_container() as container:
        hubs = await container.session().scalars(
            sa.select(Spaces.id).where(
                Spaces.user_id.is_(None), Spaces.tenant_space_id.is_(None)
            )
        )
    assert not {str(hub) for hub in hubs} & listed.keys()


async def test_without_a_default_level_nothing_is_listed(
    client, admin_headers, db_container, admin_user, levels
):
    await _shared_space(client, admin_headers, db_container, None)
    await _set_default(db_container, admin_user.tenant_id, None)

    response = await client.get(URL, headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_only_an_administrator_may_list_them(
    client, db_container, patch_auth_service_jwt, admin_user
):
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
                email=f"other-{uuid4().hex[:8]}@example.com",
                username=f"other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(user)

    response = await client.get(URL, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403, response.text
