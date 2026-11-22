"""The personal space follows the level of the owner's user groups."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table

PERSONAL_URL = "/api/v1/spaces/type/personal/"
GROUPS_URL = "/api/v1/user-groups/"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=True)
        )
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


async def _group_with_admin(client, headers, admin_user, level_id=None) -> str:
    """A group the admin user is a member of, with a level set through the API."""
    created = await client.post(
        GROUPS_URL, headers=headers, json={"name": f"unit-{uuid4().hex[:8]}"}
    )
    assert created.status_code == 200, created.text
    group_id = created.json()["id"]
    added = await client.post(
        f"{GROUPS_URL}{group_id}/users/{admin_user.id}/", headers=headers
    )
    assert added.status_code == 200, added.text
    if level_id is not None:
        response = await client.put(
            f"{GROUPS_URL}{group_id}/security-classification/",
            headers=headers,
            json={"security_classification": {"id": str(level_id)}},
        )
        assert response.status_code == 200, response.text
    return group_id


async def _personal_space(client, headers) -> dict:
    response = await client.get(PERSONAL_URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _level_of_me(client, headers) -> dict:
    response = await client.get("/api/v1/users/me/", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["effective_security_level"]


def _model_ids(space: dict) -> set[str]:
    return {model["id"] for model in space["completion_models"]}


async def test_group_without_a_level_changes_nothing(
    client, admin_headers, admin_user, models
):
    await _group_with_admin(client, admin_headers, admin_user)

    space = await _personal_space(client, admin_headers)

    assert {models["low"], models["high"], models["unclassified"]} <= _model_ids(space)
    assert space["security_classification"] is None
    assert (await _level_of_me(client, admin_headers))["source"] == "none"


async def test_group_level_cuts_what_the_personal_space_offers(
    client, admin_headers, admin_user, models
):
    group_id = await _group_with_admin(
        client, admin_headers, admin_user, models["high_level"]
    )

    space = await _personal_space(client, admin_headers)

    assert _model_ids(space) == {models["high"]}
    assert space["security_classification"]["id"] == str(models["high_level"])
    assert await _level_of_me(client, admin_headers) == {
        "security_classification_id": str(models["high_level"]),
        "source": "group",
        "user_group_id": group_id,
    }


async def test_strictest_of_the_users_groups_applies(
    client, admin_headers, admin_user, models
):
    await _group_with_admin(client, admin_headers, admin_user, models["low_level"])
    strict = await _group_with_admin(
        client, admin_headers, admin_user, models["high_level"]
    )

    space = await _personal_space(client, admin_headers)

    assert _model_ids(space) == {models["high"]}
    assert (await _level_of_me(client, admin_headers))["user_group_id"] == strict


async def test_group_below_the_default_wins_over_the_default(
    client, admin_headers, admin_user, models, db_container
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(default_user_security_classification_id=models["high_level"])
        )
    await _group_with_admin(client, admin_headers, admin_user, models["low_level"])

    space = await _personal_space(client, admin_headers)

    assert _model_ids(space) == {models["low"], models["high"]}
    assert space["security_classification"]["id"] == str(models["low_level"])


async def test_leaving_the_group_takes_its_level_away_at_once(
    client, admin_headers, admin_user, models
):
    group_id = await _group_with_admin(
        client, admin_headers, admin_user, models["high_level"]
    )
    assert _model_ids(await _personal_space(client, admin_headers)) == {models["high"]}

    removed = await client.delete(
        f"{GROUPS_URL}{group_id}/users/{admin_user.id}/", headers=admin_headers
    )
    assert removed.status_code == 200, removed.text

    space = await _personal_space(client, admin_headers)
    assert {models["low"], models["high"], models["unclassified"]} <= _model_ids(space)
    assert space["security_classification"] is None


async def test_group_level_does_nothing_while_classification_is_disabled(
    client, admin_headers, admin_user, models, db_container
):
    await _group_with_admin(client, admin_headers, admin_user, models["high_level"])
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=False)
        )

    space = await _personal_space(client, admin_headers)

    assert {models["low"], models["high"], models["unclassified"]} <= _model_ids(space)
    assert space["security_classification"] is None


async def test_shared_space_does_not_follow_the_group_level(
    client, admin_headers, admin_user, models
):
    created = await client.post(
        "/api/v1/spaces/", headers=admin_headers, json={"name": f"s-{uuid4().hex[:6]}"}
    )
    assert created.status_code == 201, created.text
    before = _model_ids(created.json())
    await _group_with_admin(client, admin_headers, admin_user, models["high_level"])

    response = await client.get(
        f"/api/v1/spaces/{created.json()['id']}/", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert models["unclassified"] in before
    assert _model_ids(response.json()) == before
    assert response.json()["security_classification"] is None


async def test_loading_a_user_with_group_levels_costs_no_extra_statement(
    db_container, admin_user, models
):
    async def statements_to_load_the_user() -> int:
        async with db_container() as container:
            session = container.session()
            count = 0

            def on_execute(*_):
                nonlocal count
                count += 1

            engine = session.bind.sync_engine
            sa.event.listen(engine, "before_cursor_execute", on_execute)
            try:
                user = await container.user_repo().get_user_by_id(admin_user.id)
            finally:
                sa.event.remove(engine, "before_cursor_execute", on_execute)
            assert user is not None
            return count

    async with db_container() as container:
        session = container.session()
        group = UserGroups(
            name=f"unit-{uuid4().hex[:8]}", tenant_id=admin_user.tenant_id
        )
        session.add(group)
        await session.flush()
        await session.execute(
            usergroups_users_table.insert().values(
                user_group_id=group.id, user_id=admin_user.id
            )
        )
        group_id = group.id
    without_level = await statements_to_load_the_user()

    async with db_container() as container:
        await container.session().execute(
            sa.update(UserGroups)
            .where(UserGroups.id == group_id)
            .values(security_classification_id=models["high_level"])
        )

    assert await statements_to_load_the_user() == without_level
