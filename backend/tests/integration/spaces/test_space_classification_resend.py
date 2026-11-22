"""Resending a space's current classification changes nothing; changing its level
still removes the model links below the new level."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.database.tables.tenant_table import Tenants


async def _classification(session, tenant_id, level: int) -> UUID:
    row = SecurityClassification(
        name=f"level-{level}-{uuid4().hex[:6]}",
        security_level=level,
        tenant_id=tenant_id,
    )
    session.add(row)
    await session.flush()
    return row.id


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def setup(
    db_container, admin_user, completion_model_factory, client, admin_headers
):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=True)
        )
        low = await _classification(session, admin_user.tenant_id, 1)
        high = await _classification(session, admin_user.tenant_id, 2)
        top = await _classification(session, admin_user.tenant_id, 3)
        model = await completion_model_factory(
            session, "model", security_classification_id=high
        )
        model_id = model.id
    response = await client.post(
        "/api/v1/spaces/", headers=admin_headers, json={"name": f"s-{uuid4().hex[:6]}"}
    )
    assert response.status_code == 201, response.text
    return {
        "space_id": response.json()["id"],
        "model_id": model_id,
        "low": low,
        "high": high,
        "top": top,
    }


async def _link_exists(db_container, space_id, model_id) -> bool:
    async with db_container() as container:
        count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(SpacesCompletionModels)
            .where(
                SpacesCompletionModels.space_id == space_id,
                SpacesCompletionModels.completion_model_id == model_id,
            )
        )
        return bool(count)


async def _classify_model(db_container, model_id, classification_id) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == model_id)
            .values(security_classification_id=classification_id)
        )


async def _patch(client, headers, space_id, classification_id):
    return await client.patch(
        f"/api/v1/spaces/{space_id}/",
        headers=headers,
        json={"security_classification": {"id": str(classification_id)}},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restating_the_classification_keeps_the_model_links(
    client, admin_headers, db_container, setup
):
    space_id, model_id = setup["space_id"], setup["model_id"]
    assert (
        await _patch(client, admin_headers, space_id, setup["high"])
    ).status_code == 200
    assert await _link_exists(db_container, space_id, model_id)
    await _classify_model(db_container, model_id, setup["low"])

    response = await _patch(client, admin_headers, space_id, setup["high"])

    assert response.status_code == 200, response.text
    assert await _link_exists(db_container, space_id, model_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_raising_the_level_removes_the_links_below_it(
    client, admin_headers, db_container, setup
):
    space_id, model_id = setup["space_id"], setup["model_id"]
    assert (
        await _patch(client, admin_headers, space_id, setup["high"])
    ).status_code == 200
    assert await _link_exists(db_container, space_id, model_id)

    response = await _patch(client, admin_headers, space_id, setup["top"])

    assert response.status_code == 200, response.text
    assert not await _link_exists(db_container, space_id, model_id)
