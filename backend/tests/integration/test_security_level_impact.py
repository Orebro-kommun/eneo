"""The preview of a user level: GET /api/v1/security-classifications/level-impact/."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.service_table import Services
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

IMPACT_URL = "/api/v1/security-classifications/level-impact/"
DEFAULT_URL = "/api/v1/security-classifications/default-user-level/"

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def other_user(db_container, admin_user):
    """A second user without the admin permission and without groups."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"non-admin-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"other-{uuid4().hex[:8]}@example.com",
                username=f"other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


@pytest.fixture
async def world(
    db_container,
    admin_user,
    other_user,
    completion_model_factory,
    embedding_model_factory,
    transcription_model_factory,
):
    """Levels 1-3, a model of each kind at 1 and 2, and a group holding the admin."""
    async with db_container() as container:
        session = container.session()
        levels = []
        for level in (1, 2, 3):
            row = SecurityClassification(
                name=f"level-{level}-{uuid4().hex[:6]}",
                security_level=level,
                tenant_id=admin_user.tenant_id,
            )
            session.add(row)
            await session.flush()
            levels.append(row.id)
        low, high, top = levels
        ids = {"low_level": low, "high_level": high, "top_level": top}
        for kind, factory in (
            ("chat", completion_model_factory),
            ("embedding", embedding_model_factory),
            ("transcription", transcription_model_factory),
        ):
            for name, level in (("low", low), ("high", high)):
                model = await factory(
                    session,
                    f"{kind}-{name}-{uuid4().hex[:6]}",
                    security_classification_id=level,
                )
                ids[f"{name}_{kind}"] = model.id
        group = UserGroups(name=f"g-{uuid4().hex[:6]}", tenant_id=admin_user.tenant_id)
        session.add(group)
        await session.flush()
        await session.execute(
            sa.insert(usergroups_users_table).values(
                user_id=admin_user.id, user_group_id=group.id
            )
        )
        ids["group"] = group.id
        ids["users"] = await session.scalar(
            sa.select(sa.func.count())
            .select_from(Users)
            .where(Users.tenant_id == admin_user.tenant_id, Users.deleted_at.is_(None))
        )
        return ids


async def _set_default(db_container, tenant_id, classification_id) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                security_enabled=True,
                default_user_security_classification_id=classification_id,
            )
        )


async def _impact(client, headers, classification_id=None, group_id=None) -> dict:
    params = {}
    if classification_id is not None:
        params["security_classification_id"] = str(classification_id)
    if group_id is not None:
        params["user_group_id"] = str(group_id)
    response = await client.get(IMPACT_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _personal_resources(client, headers, db_container, world) -> None:
    """In the admin's personal space: one resource per model below, one above."""
    personal = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    base = f"/api/v1/spaces/{personal.json()['id']}"

    async def create(path: str, body: dict | None = None) -> UUID:
        response = await client.post(
            f"{base}/{path}/",
            headers=headers,
            json={"name": f"r-{uuid4().hex[:6]}", **(body or {})},
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["id"])

    low_assistant = await create("applications/assistants")
    high_assistant = await create("applications/assistants")
    service = await create("applications/services")
    low_app = await create("applications/apps")
    transcribing_app = await create("applications/apps")
    low_collection = await create("knowledge/groups")
    high_collection = await create("knowledge/groups")

    async with db_container() as container:
        session = container.session()
        # The default assistant picks a model by itself; keep it out of the counts.
        await session.execute(
            sa.update(Assistants)
            .where(
                Assistants.space_id == UUID(personal.json()["id"]),
                Assistants.is_default.is_(True),
            )
            .values(completion_model_id=None)
        )
        for table, row_id, values in (
            (Assistants, low_assistant, {"completion_model_id": world["low_chat"]}),
            (Assistants, high_assistant, {"completion_model_id": world["high_chat"]}),
            (Services, service, {"completion_model_id": world["low_chat"]}),
            (
                CollectionsTable,
                low_collection,
                {"embedding_model_id": world["low_embedding"]},
            ),
            (
                CollectionsTable,
                high_collection,
                {"embedding_model_id": world["high_embedding"]},
            ),
            (
                Apps,
                low_app,
                {
                    "completion_model_id": world["low_chat"],
                    "transcription_model_id": world["high_transcription"],
                },
            ),
            (
                Apps,
                transcribing_app,
                {
                    "completion_model_id": world["high_chat"],
                    "transcription_model_id": world["low_transcription"],
                },
            ),
        ):
            await session.execute(
                sa.update(table).where(table.id == row_id).values(**values)
            )
        # The personal default assistant is repaired, so it is never counted.
        await session.execute(
            sa.update(Assistants)
            .where(
                Assistants.space_id == UUID(personal.json()["id"]),
                Assistants.is_default.is_(True),
            )
            .values(completion_model_id=world["low_chat"])
        )


async def test_a_default_level_counts_every_user_and_what_falls_below_it(
    client, admin_headers, db_container, admin_user, world
):
    await _personal_resources(client, admin_headers, db_container, world)
    await _set_default(db_container, admin_user.tenant_id, world["low_level"])

    impact = await _impact(client, admin_headers, world["high_level"])

    assert impact["affected_users"] == world["users"]
    assert impact["assistants"] == 1
    assert impact["services"] == 1
    assert impact["apps"] == 2
    assert impact["knowledge_sources"] == 1
    assert impact["completion_models"] == 1
    assert impact["transcription_models"] == 1


async def test_a_group_level_counts_only_the_members(
    client, admin_headers, db_container, admin_user, world
):
    await _personal_resources(client, admin_headers, db_container, world)
    await _set_default(db_container, admin_user.tenant_id, world["low_level"])

    impact = await _impact(client, admin_headers, world["high_level"], world["group"])

    assert impact["affected_users"] == 1
    assert (impact["assistants"], impact["services"], impact["apps"]) == (1, 1, 2)


async def test_a_group_level_below_the_default_changes_its_members(
    client, admin_headers, db_container, admin_user, world
):
    await _personal_resources(client, admin_headers, db_container, world)
    await _set_default(db_container, admin_user.tenant_id, world["high_level"])

    impact = await _impact(client, admin_headers, world["low_level"], world["group"])

    assert impact["affected_users"] == 1
    assert (impact["assistants"], impact["services"], impact["apps"]) == (0, 0, 0)


async def test_what_the_current_level_already_stops_is_not_counted(
    client, admin_headers, db_container, admin_user, world
):
    await _personal_resources(client, admin_headers, db_container, world)
    await _set_default(db_container, admin_user.tenant_id, world["high_level"])

    impact = await _impact(client, admin_headers, world["top_level"])

    # Only what met level 2 falls: the assistant on the level-2 model.
    assert impact["affected_users"] == world["users"]
    assert (impact["assistants"], impact["services"], impact["apps"]) == (1, 0, 0)
    assert impact["completion_models"] == 0


async def test_the_level_already_in_force_changes_nothing(
    client, admin_headers, db_container, admin_user, world
):
    await _set_default(db_container, admin_user.tenant_id, world["high_level"])

    impact = await _impact(client, admin_headers, world["high_level"])

    assert impact["affected_users"] == 0


async def test_a_member_of_a_group_with_a_level_does_not_follow_the_default(
    client, admin_headers, db_container, admin_user, world
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(UserGroups)
            .where(UserGroups.id == world["group"])
            .values(security_classification_id=world["low_level"])
        )

    impact = await _impact(client, admin_headers, world["high_level"])

    assert impact["affected_users"] == world["users"] - 1


async def test_clearing_the_default_changes_every_user_and_stops_nothing(
    client, admin_headers, db_container, admin_user, world
):
    await _personal_resources(client, admin_headers, db_container, world)
    await _set_default(db_container, admin_user.tenant_id, world["high_level"])

    impact = await _impact(client, admin_headers)

    assert impact["affected_users"] == world["users"]
    assert (impact["assistants"], impact["services"], impact["apps"]) == (0, 0, 0)
    assert impact["knowledge_sources"] == 0


async def test_an_unknown_group_or_classification_is_not_found(
    client, admin_headers, world
):
    for params in (
        {"security_classification_id": str(uuid4())},
        {"user_group_id": str(uuid4())},
    ):
        response = await client.get(IMPACT_URL, headers=admin_headers, params=params)
        assert response.status_code == 404, response.text


async def test_the_preview_is_for_administrators(
    client, db_container, patch_auth_service_jwt, other_user, world
):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(other_user)

    response = await client.get(
        IMPACT_URL, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403, response.text


async def test_a_default_no_completion_model_meets_is_refused(
    client, admin_headers, db_container, admin_user, world
):
    response = await client.put(
        DEFAULT_URL,
        headers=admin_headers,
        json={"security_classification": {"id": str(world["top_level"])}},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "default_level_without_model"
    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(Tenants.default_user_security_classification_id).where(
                Tenants.id == admin_user.tenant_id
            )
        )
    assert stored is None


async def test_an_administrator_reads_a_users_level_and_its_source(
    client, admin_headers, db_container, admin_user, other_user, world
):
    await _set_default(db_container, admin_user.tenant_id, world["low_level"])
    async with db_container() as container:
        await container.session().execute(
            sa.update(UserGroups)
            .where(UserGroups.id == world["group"])
            .values(security_classification_id=world["high_level"])
        )

    by_group = await client.get(
        f"/api/v1/admin/users/{admin_user.username}/", headers=admin_headers
    )
    by_default = await client.get(
        f"/api/v1/admin/users/{other_user.username}/", headers=admin_headers
    )

    assert (by_group.status_code, by_default.status_code) == (200, 200)
    assert by_group.json()["effective_security_level"] == {
        "security_classification_id": str(world["high_level"]),
        "source": "group",
        "user_group_id": str(world["group"]),
    }
    assert by_default.json()["effective_security_level"] == {
        "security_classification_id": str(world["low_level"]),
        "source": "default",
        "user_group_id": None,
    }
