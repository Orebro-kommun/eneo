"""A space administrator may not set a shared space's level below their own."""

from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from tests.integration.spaces.security_level_setup import (
    SPACES_URL,
    classification,
    create_space,
    headers_for,
    member,
    set_tenant,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    return await headers_for(db_container, admin_user)


@pytest.fixture
async def headers(db_container, patch_auth_service_jwt, admin_user):
    return await headers_for(db_container, await member(db_container, admin_user))


@pytest.fixture
async def levels(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        ids = {
            name: await classification(session, admin_user.tenant_id, level)
            for level, name in enumerate(("low", "high", "top"), start=1)
        }
    await set_tenant(db_container, admin_user.tenant_id, security_enabled=True)
    return ids


async def _work_at(db_container, admin_user, level_id) -> None:
    await set_tenant(
        db_container,
        admin_user.tenant_id,
        default_user_security_classification_id=level_id,
    )


async def _set_level(client, headers, space_id, level_id):
    return await client.patch(
        f"{SPACES_URL}{space_id}/",
        headers=headers,
        json={"security_classification": {"id": str(level_id)} if level_id else None},
    )


async def _stored_level(db_container, space_id):
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == UUID(space_id)
            )
        )


async def test_administrator_may_raise_and_lower_to_their_own_level_but_not_below(
    client, headers, db_container, admin_user, levels
):
    await _work_at(db_container, admin_user, levels["high"])
    space_id = (await create_space(client, headers))["id"]

    raised = await _set_level(client, headers, space_id, levels["top"])
    assert raised.status_code == 200, raised.text
    lowered = await _set_level(client, headers, space_id, levels["high"])
    assert lowered.status_code == 200, lowered.text

    below = await _set_level(client, headers, space_id, levels["low"])
    removed = await _set_level(client, headers, space_id, None)

    for refused in (below, removed):
        assert refused.status_code == 403, refused.text
        assert "below your own security level" in refused.text
    assert await _stored_level(db_container, space_id) == levels["high"]


async def test_a_space_already_below_the_level_can_still_be_saved(
    client, headers, db_container, admin_user, levels
):
    space_id = (await create_space(client, headers))["id"]
    await _work_at(db_container, admin_user, levels["high"])

    response = await client.patch(
        f"{SPACES_URL}{space_id}/",
        headers=headers,
        json={"name": "Renamed", "security_classification": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed"
    assert await _stored_level(db_container, space_id) is None


async def test_administrator_without_a_level_may_lower_and_remove(
    client, headers, db_container, levels
):
    space_id = (await create_space(client, headers))["id"]
    assert (
        await _set_level(client, headers, space_id, levels["top"])
    ).status_code == 200

    lowered = await _set_level(client, headers, space_id, levels["low"])
    assert lowered.status_code == 200, lowered.text
    removed = await _set_level(client, headers, space_id, None)
    assert removed.status_code == 200, removed.text
    assert await _stored_level(db_container, space_id) is None


async def test_organisation_administrator_is_exempt(
    client, admin_headers, db_container, admin_user, levels
):
    await _work_at(db_container, admin_user, levels["high"])
    space_id = (await create_space(client, admin_headers))["id"]

    response = await _set_level(client, admin_headers, space_id, levels["low"])

    assert response.status_code == 200, response.text
    assert await _stored_level(db_container, space_id) == levels["low"]


async def test_space_editor_cannot_change_the_level(
    client, headers, db_container, admin_user, levels
):
    space_id = (await create_space(client, headers))["id"]
    editor = await member(db_container, admin_user)
    async with db_container() as container:
        await container.session().execute(
            sa.insert(SpacesUsers).values(
                space_id=UUID(space_id), user_id=editor.id, role="editor"
            )
        )

    response = await _set_level(
        client, await headers_for(db_container, editor), space_id, levels["top"]
    )

    assert response.status_code == 403, response.text
    assert await _stored_level(db_container, space_id) is None
