"""The personal space the API returns follows the organisation's default level."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants

PERSONAL_URL = "/api/v1/spaces/type/personal/"


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
async def models(db_container, admin_user, completion_model_factory):
    """One model per level (1 and 2) and one without a classification."""
    async with db_container() as container:
        session = container.session()
        low = await _classification(session, admin_user.tenant_id, 1)
        high = await _classification(session, admin_user.tenant_id, 2)
        low_model = await completion_model_factory(
            session, "low", security_classification_id=low
        )
        high_model = await completion_model_factory(
            session, "high", security_classification_id=high
        )
        open_model = await completion_model_factory(session, "open")
        return {
            "low_level": low,
            "high_level": high,
            "low": str(low_model.id),
            "high": str(high_model.id),
            "unclassified": str(open_model.id),
        }


async def _set_tenant(db_container, tenant_id, **values) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants).where(Tenants.id == tenant_id).values(**values)
        )


async def _personal_space(client, headers) -> dict:
    response = await client.get(PERSONAL_URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _model_ids(space: dict) -> set[str]:
    return {model["id"] for model in space["completion_models"]}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_without_a_level_the_personal_space_offers_every_model(
    client, admin_headers, db_container, admin_user, models
):
    await _set_tenant(db_container, admin_user.tenant_id, security_enabled=True)

    space = await _personal_space(client, admin_headers)

    assert {models["low"], models["high"], models["unclassified"]} <= _model_ids(space)
    assert space["security_classification"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_default_level_cuts_what_the_personal_space_offers(
    client, admin_headers, db_container, admin_user, models
):
    before = _model_ids(await _personal_space(client, admin_headers))
    await _set_tenant(
        db_container,
        admin_user.tenant_id,
        security_enabled=True,
        default_user_security_classification_id=models["high_level"],
    )

    space = await _personal_space(client, admin_headers)

    assert {models["low"], models["high"], models["unclassified"]} <= before
    assert _model_ids(space) == {models["high"]}
    assert space["security_classification"]["id"] == str(models["high_level"])
    # The floor is computed: nothing is stored on the space.
    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == UUID(space["id"])
            )
        )
    assert stored is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_default_level_does_nothing_while_classification_is_disabled(
    client, admin_headers, db_container, admin_user, models
):
    await _set_tenant(
        db_container,
        admin_user.tenant_id,
        security_enabled=False,
        default_user_security_classification_id=models["high_level"],
    )

    space = await _personal_space(client, admin_headers)

    assert {models["low"], models["high"], models["unclassified"]} <= _model_ids(space)
    assert space["security_classification"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_shared_space_does_not_follow_the_default_level(
    client, admin_headers, db_container, admin_user, models
):
    created = await client.post(
        "/api/v1/spaces/", headers=admin_headers, json={"name": f"s-{uuid4().hex[:6]}"}
    )
    assert created.status_code == 201, created.text
    before = _model_ids(created.json())
    await _set_tenant(
        db_container,
        admin_user.tenant_id,
        security_enabled=True,
        default_user_security_classification_id=models["high_level"],
    )

    response = await client.get(
        f"/api/v1/spaces/{created.json()['id']}/", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert models["unclassified"] in before
    assert _model_ids(response.json()) == before
    assert response.json()["security_classification"] is None
