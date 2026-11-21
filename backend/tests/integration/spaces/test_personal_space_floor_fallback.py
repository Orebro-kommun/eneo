"""A stored model below the owner's security level is replaced on the personal
default assistant, and refused with the reason on any other personal assistant."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants
from eneo.main.exceptions import ErrorCodes


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def models(db_container, admin_user, completion_model_factory):
    """A model at level 1 and one at level 2; the tenant's default level is 2."""
    async with db_container() as container:
        session = container.session()
        levels = []
        for level in (1, 2):
            row = SecurityClassification(
                name=f"level-{level}-{uuid4().hex[:6]}",
                security_level=level,
                tenant_id=admin_user.tenant_id,
            )
            session.add(row)
            await session.flush()
            levels.append(row.id)
        low = await completion_model_factory(
            session, "low", security_classification_id=levels[0]
        )
        high = await completion_model_factory(
            session, "high", security_classification_id=levels[1]
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(
                security_enabled=True,
                default_user_security_classification_id=levels[1],
            )
        )
        return {"low": low.id, "high": high.id}


async def _store_model(db_container, assistant_id: UUID, model_id: UUID) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(completion_model_id=model_id)
        )


async def _default_assistant_id(db_container) -> UUID:
    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assert space.default_assistant is not None
        return space.default_assistant.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_default_assistant_is_moved_off_a_model_below_the_level(
    db_container, admin_user, models
):
    assistant_id = await _default_assistant_id(db_container)
    await _store_model(db_container, assistant_id, models["low"])

    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.completion_model is not None
        assert assistant.completion_model.id == models["high"]

        row = await container.session().get(Assistants, assistant_id)
        assert row is not None
        assert row.completion_model_id == models["high"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_default_assistant_keeps_a_model_that_meets_the_level(
    db_container, admin_user, models
):
    assistant_id = await _default_assistant_id(db_container)
    await _store_model(db_container, assistant_id, models["high"])

    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assert space.default_assistant is not None
        assert space.default_assistant.completion_model is not None
        assert space.default_assistant.completion_model.id == models["high"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_asking_a_personal_assistant_below_the_level_says_why(
    client, admin_headers, db_container, admin_user, models
):
    personal = await client.get("/api/v1/spaces/type/personal/", headers=admin_headers)
    assert personal.status_code == 200, personal.text
    created = await client.post(
        f"/api/v1/spaces/{personal.json()['id']}/applications/assistants/",
        headers=admin_headers,
        json={"name": f"a-{uuid4().hex[:6]}"},
    )
    assert created.status_code == 201, created.text
    assistant_id = UUID(created.json()["id"])
    await _store_model(db_container, assistant_id, models["low"])

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/sessions/",
        headers=admin_headers,
        json={"question": "hello"},
    )

    assert response.status_code == 400, response.text
    assert (
        response.json()["eneo_error_code"]
        == ErrorCodes.SECURITY_CLASSIFICATION_MISMATCH
    )
