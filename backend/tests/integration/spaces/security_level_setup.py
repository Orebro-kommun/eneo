"""Setup shared by the tests of the security level rules for shared spaces."""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

SPACES_URL = "/api/v1/spaces/"


async def classification(session, tenant_id, level: int) -> UUID:
    row = SecurityClassification(
        name=f"level-{level}-{uuid4().hex[:6]}",
        security_level=level,
        tenant_id=tenant_id,
    )
    session.add(row)
    await session.flush()
    return row.id


async def headers_for(db_container, user) -> dict[str, str]:
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
        return {"Authorization": f"Bearer {token}"}


async def member(db_container, admin_user):
    """A user who may create shared spaces and assistants but is no administrator."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.SHARED_SPACES, Permission.ASSISTANTS],
                tenant_id=admin_user.tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


async def set_tenant(db_container, tenant_id, **values) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants).where(Tenants.id == tenant_id).values(**values)
        )


async def create_space(client, headers) -> dict:
    response = await client.post(
        SPACES_URL, headers=headers, json={"name": f"s-{uuid4().hex[:6]}"}
    )
    assert response.status_code == 201, response.text
    return response.json()
