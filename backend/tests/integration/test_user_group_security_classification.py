"""A user group's level: PUT /api/v1/user-groups/{id}/security-classification/."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.user_groups_table import UserGroups
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

GROUPS_URL = "/api/v1/user-groups/"
CLASSIFICATIONS_URL = "/api/v1/security-classifications/"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _level_url(group_id) -> str:
    return f"{GROUPS_URL}{group_id}/security-classification/"


def _body(classification_id) -> dict:
    return {"security_classification": {"id": str(classification_id)}}


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


@pytest.fixture
async def group_id(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        row = UserGroups(name=f"unit-{uuid4().hex[:8]}", tenant_id=admin_user.tenant_id)
        session.add(row)
        await session.flush()
        return row.id


async def _stored_level(db_container, group_id):
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(UserGroups.security_classification_id).where(
                UserGroups.id == group_id
            )
        )


async def test_new_group_has_no_level(client, admin_headers, group_id):
    read = await client.get(f"{GROUPS_URL}{group_id}/", headers=admin_headers)

    assert read.status_code == 200, read.text
    assert read.json()["security_classification_id"] is None


async def test_level_is_read_once_set_and_gone_once_cleared(
    client, admin_headers, group_id, classification_id
):
    set_response = await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["id"] == str(group_id)
    assert set_response.json()["security_classification_id"] == str(classification_id)
    read = await client.get(f"{GROUPS_URL}{group_id}/", headers=admin_headers)
    assert read.json()["security_classification_id"] == str(classification_id)

    cleared = await client.put(
        _level_url(group_id),
        headers=admin_headers,
        json={"security_classification": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["security_classification_id"] is None
    read = await client.get(f"{GROUPS_URL}{group_id}/", headers=admin_headers)
    assert read.json()["security_classification_id"] is None


async def test_level_must_be_an_existing_classification(
    client, admin_headers, group_id
):
    response = await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(uuid4())
    )

    assert response.status_code == 404, response.text


async def test_level_cannot_be_set_on_an_unknown_group(
    client, admin_headers, classification_id
):
    response = await client.put(
        _level_url(uuid4()), headers=admin_headers, json=_body(classification_id)
    )

    assert response.status_code == 404, response.text


async def test_non_admin_cannot_set_a_group_level(
    client, non_admin_headers, group_id, classification_id, db_container
):
    response = await client.put(
        _level_url(group_id), headers=non_admin_headers, json=_body(classification_id)
    )

    assert response.status_code == 403, response.text
    assert await _stored_level(db_container, group_id) is None


async def test_list_open_to_every_member_does_not_show_the_level(
    client, admin_headers, non_admin_headers, group_id, classification_id
):
    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )

    listed = await client.get(GROUPS_URL, headers=non_admin_headers)

    assert listed.status_code == 200, listed.text
    groups = {group["id"]: group for group in listed.json()["items"]}
    assert "security_classification_id" not in groups[str(group_id)]


async def test_renaming_the_group_keeps_its_level(
    client, admin_headers, group_id, classification_id, db_container
):
    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )

    renamed = await client.post(
        f"{GROUPS_URL}{group_id}/",
        headers=admin_headers,
        json={"name": f"renamed-{uuid4().hex[:8]}"},
    )

    assert renamed.status_code == 200, renamed.text
    assert await _stored_level(db_container, group_id) == classification_id


async def test_setting_the_level_is_audited(
    client, admin_headers, group_id, classification_id, monkeypatch
):
    logged: list[dict] = []

    async def record(self, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)

    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )

    [entry] = [call for call in logged if call["entity_id"] == group_id]
    assert entry["action"] == ActionType.TENANT_SETTINGS_UPDATED
    assert entry["entity_type"] == EntityType.USER_GROUP
    assert entry["metadata"]["changes"] == {
        "security_classification_id": {"old": None, "new": str(classification_id)}
    }


async def test_classification_used_by_a_group_cannot_be_deleted_by_mistake(
    client, admin_headers, group_id, classification_id, db_container
):
    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )

    response = await client.delete(
        f"{CLASSIFICATIONS_URL}{classification_id}/", headers=admin_headers
    )

    assert response.status_code == 400, response.text
    assert "user_groups" in response.text
    assert await _stored_level(db_container, group_id) == classification_id


async def test_forced_delete_clears_the_group_level(
    client, admin_headers, group_id, classification_id, db_container
):
    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )

    response = await client.delete(
        f"{CLASSIFICATIONS_URL}{classification_id}/?force=true", headers=admin_headers
    )

    assert response.status_code == 204, response.text
    assert await _stored_level(db_container, group_id) is None


async def test_deleted_group_does_not_hold_back_a_classification(
    client, admin_headers, group_id, classification_id, db_container
):
    await client.put(
        _level_url(group_id), headers=admin_headers, json=_body(classification_id)
    )
    async with db_container() as container:
        await container.session().execute(
            sa.update(UserGroups)
            .where(UserGroups.id == group_id)
            .values(state="deleted")
        )

    response = await client.delete(
        f"{CLASSIFICATIONS_URL}{classification_id}/", headers=admin_headers
    )

    assert response.status_code == 204, response.text
