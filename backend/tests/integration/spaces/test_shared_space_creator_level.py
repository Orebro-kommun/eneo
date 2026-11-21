"""A new shared space starts at its creator's security level."""

from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.spaces_table import Spaces
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
async def headers(db_container, patch_auth_service_jwt, admin_user):
    return await headers_for(db_container, await member(db_container, admin_user))


@pytest.fixture
async def setup(db_container, admin_user, completion_model_factory):
    """Models and MCP servers at level 1, level 2 and without a classification."""
    async with db_container() as container:
        session = container.session()
        levels = {
            "low": await classification(session, admin_user.tenant_id, 1),
            "high": await classification(session, admin_user.tenant_id, 2),
            "unclassified": None,
        }
        models, servers = {}, {}
        for name, level in levels.items():
            model = await completion_model_factory(
                session, f"model-{name}", security_classification_id=level
            )
            models[name] = str(model.id)
            server = MCPServers(
                tenant_id=admin_user.tenant_id,
                name=f"server-{name}",
                http_url="http://localhost:9000/mcp",
                http_auth_type="none",
                is_enabled=True,
                forward_identity=False,
                security_classification_id=level,
            )
            session.add(server)
            await session.flush()
            servers[name] = str(server.id)
    return {"levels": levels, "models": models, "servers": servers}


def _ids(space: dict, key: str) -> set[str]:
    return {str(item["id"]) for item in space[key]}


async def test_a_new_space_starts_at_its_creators_level(
    client, headers, db_container, admin_user, setup
):
    high = setup["levels"]["high"]
    await set_tenant(
        db_container,
        admin_user.tenant_id,
        security_enabled=True,
        default_user_security_classification_id=high,
    )

    created = await create_space(client, headers)

    assert created["security_classification"]["id"] == str(high)
    assert _ids(created, "completion_models") == {setup["models"]["high"]}
    assert _ids(created, "mcp_servers") == {setup["servers"]["high"]}

    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(Spaces.security_classification_id).where(
                Spaces.id == UUID(created["id"])
            )
        )
    assert stored == high

    reloaded = await client.get(f"{SPACES_URL}{created['id']}/", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["security_classification"]["id"] == str(high)
    assert _ids(reloaded.json(), "completion_models") == {setup["models"]["high"]}
    assert _ids(reloaded.json(), "mcp_servers") == {setup["servers"]["high"]}


async def test_without_a_level_a_new_space_has_no_classification(
    client, headers, db_container, admin_user, setup
):
    await set_tenant(db_container, admin_user.tenant_id, security_enabled=True)

    created = await create_space(client, headers)

    assert created["security_classification"] is None
    assert set(setup["models"].values()) <= _ids(created, "completion_models")
    assert _ids(created, "mcp_servers") == set(setup["servers"].values())
