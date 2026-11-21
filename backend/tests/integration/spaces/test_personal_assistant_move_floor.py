"""An assistant may not leave a personal space for a space below its owner's level."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
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
async def high(db_container, admin_user, completion_model_factory):
    """Level 2, with a model that meets it."""
    async with db_container() as container:
        session = container.session()
        level = await classification(session, admin_user.tenant_id, 2)
        await completion_model_factory(
            session, "high model", security_classification_id=level
        )
    await set_tenant(db_container, admin_user.tenant_id, security_enabled=True)
    return level


async def _work_at(db_container, admin_user, level_id) -> None:
    await set_tenant(
        db_container,
        admin_user.tenant_id,
        default_user_security_classification_id=level_id,
    )


async def _personal_assistant(client, headers) -> str:
    personal = await client.get(f"{SPACES_URL}type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    created = await client.post(
        f"{SPACES_URL}{personal.json()['id']}/applications/assistants/",
        headers=headers,
        json={"name": f"a-{uuid4().hex[:6]}"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _transfer(client, headers, assistant_id, space_id):
    return await client.post(
        f"/api/v1/assistants/{assistant_id}/transfer/",
        headers=headers,
        json={"target_space_id": space_id},
    )


async def _space_of(db_container, assistant_id) -> str:
    async with db_container() as container:
        return str(
            await container.session().scalar(
                sa.select(Assistants.space_id).where(
                    Assistants.id == UUID(assistant_id)
                )
            )
        )


async def test_move_from_personal_space_follows_the_users_level(
    client, headers, db_container, admin_user, high
):
    unclassified = (await create_space(client, headers))["id"]
    await _work_at(db_container, admin_user, high)
    at_level = (await create_space(client, headers))["id"]
    assistant_id = await _personal_assistant(client, headers)
    personal = await _space_of(db_container, assistant_id)

    refused = await _transfer(client, headers, assistant_id, unclassified)

    assert refused.status_code == 403, refused.text
    assert "below your security level" in refused.text
    assert await _space_of(db_container, assistant_id) == personal

    allowed = await _transfer(client, headers, assistant_id, at_level)

    assert allowed.status_code == 204, allowed.text
    assert await _space_of(db_container, assistant_id) == at_level

    # Between two shared spaces the user's level plays no part.
    onwards = await _transfer(client, headers, assistant_id, unclassified)

    assert onwards.status_code == 204, onwards.text
    assert await _space_of(db_container, assistant_id) == unclassified


async def test_without_a_level_an_assistant_leaves_the_personal_space_as_before(
    client, headers, db_container, high
):
    unclassified = (await create_space(client, headers))["id"]
    assistant_id = await _personal_assistant(client, headers)

    response = await _transfer(client, headers, assistant_id, unclassified)

    assert response.status_code == 204, response.text
    assert await _space_of(db_container, assistant_id) == unclassified


async def test_organisation_administrator_is_exempt(
    client, admin_headers, db_container, admin_user, high
):
    unclassified = (await create_space(client, admin_headers))["id"]
    await _work_at(db_container, admin_user, high)
    assistant_id = await _personal_assistant(client, admin_headers)

    response = await _transfer(client, admin_headers, assistant_id, unclassified)

    assert response.status_code == 204, response.text
    assert await _space_of(db_container, assistant_id) == unclassified
