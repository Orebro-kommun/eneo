"""SCIM owns a group's name and members, never its security level."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.security_classifications.domain.effective_level import (
    effective_security_level,
)

_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def classification_id(db_session, test_tenant):
    async with db_session() as session:
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == test_tenant.id)
            .values(security_enabled=True)
        )
        row = SecurityClassification(
            name=f"internal-{uuid4().hex[:8]}",
            security_level=0,
            tenant_id=test_tenant.id,
        )
        session.add(row)
        await session.flush()
        return row.id


@pytest.fixture
async def group_with_level(db_session, scim_group, classification_id):
    async with db_session() as session:
        await session.execute(
            sa.update(UserGroups)
            .where(UserGroups.id == scim_group.id)
            .values(security_classification_id=classification_id)
        )
    return scim_group


async def _stored_level(db_session, group_id):
    async with db_session() as session:
        return await session.scalar(
            sa.select(UserGroups.security_classification_id).where(
                UserGroups.id == group_id
            )
        )


async def _level_of(db_container, user_id):
    async with db_container() as container:
        user = await container.user_repo().get_user_by_id(user_id)
        return effective_security_level(user)


async def test_replacing_the_group_keeps_its_level(
    client, bypass_scim_auth, db_session, group_with_level, classification_id
):
    response = await client.put(
        f"/scim/v2/Groups/{group_with_level.id}",
        json={
            "schemas": [_GROUP_SCHEMA],
            "externalId": "grp-renamed",
            "displayName": "Renamed by the IdP",
            "members": [],
        },
    )

    assert response.status_code == 200, response.text
    assert await _stored_level(db_session, group_with_level.id) == classification_id


async def test_renaming_the_group_keeps_its_level(
    client, bypass_scim_auth, db_session, group_with_level, classification_id
):
    response = await client.patch(
        f"/scim/v2/Groups/{group_with_level.id}",
        json={
            "schemas": [_PATCH_SCHEMA],
            "Operations": [
                {"op": "replace", "path": "displayName", "value": "Renamed"}
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert await _stored_level(db_session, group_with_level.id) == classification_id


async def test_membership_change_keeps_the_level_and_moves_the_user(
    client,
    bypass_scim_auth,
    db_session,
    db_container,
    group_with_level,
    scim_user,
    classification_id,
):
    assert (await _level_of(db_container, scim_user.id)).source == "none"

    added = await client.patch(
        f"/scim/v2/Groups/{group_with_level.id}",
        json={
            "schemas": [_PATCH_SCHEMA],
            "Operations": [
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": str(scim_user.id)}],
                }
            ],
        },
    )

    assert added.status_code == 200, added.text
    assert await _stored_level(db_session, group_with_level.id) == classification_id
    level = await _level_of(db_container, scim_user.id)
    assert level.security_classification_id == classification_id
    assert level.user_group_id == group_with_level.id

    removed = await client.patch(
        f"/scim/v2/Groups/{group_with_level.id}",
        json={
            "schemas": [_PATCH_SCHEMA],
            "Operations": [
                {"op": "remove", "path": f'members[value eq "{scim_user.id}"]'}
            ],
        },
    )

    assert removed.status_code == 200, removed.text
    assert await _stored_level(db_session, group_with_level.id) == classification_id
    assert (await _level_of(db_container, scim_user.id)).source == "none"


async def test_group_deleted_by_the_idp_stops_counting(
    client, bypass_scim_auth, db_session, db_container, group_with_level, scim_user
):
    async with db_session() as session:
        await session.execute(
            usergroups_users_table.insert().values(
                user_group_id=group_with_level.id, user_id=scim_user.id
            )
        )
    assert (await _level_of(db_container, scim_user.id)).source == "group"

    deleted = await client.delete(f"/scim/v2/Groups/{group_with_level.id}")

    assert deleted.status_code == 204, deleted.text
    assert (await _level_of(db_container, scim_user.id)).source == "none"


async def test_group_created_again_under_the_same_name_gets_its_level_back(
    client, bypass_scim_auth, db_session, group_with_level, classification_id
):
    deleted = await client.delete(f"/scim/v2/Groups/{group_with_level.id}")
    assert deleted.status_code == 204, deleted.text

    created = await client.post(
        "/scim/v2/Groups",
        json={
            "schemas": [_GROUP_SCHEMA],
            "externalId": "grp-scim-002",
            "displayName": group_with_level.name,
            "members": [],
        },
    )

    # The soft-deleted row is reactivated, so the level set in Eneo survives.
    assert created.status_code == 201, created.text
    assert created.json()["id"] == str(group_with_level.id)
    assert await _stored_level(db_session, group_with_level.id) == classification_id
