"""A space administrator may not set a shared space's level below their own."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces import space_service
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_service import SpaceService
from tests.fixtures import TEST_TENANT, TEST_USER

TENANT = TEST_TENANT.model_copy(update={"security_enabled": True})
MEMBER = TEST_USER.model_copy(
    update={
        "tenant": TENANT,
        "roles": [
            RoleInDB(
                id=uuid4(),
                name="Member",
                permissions=[Permission.SHARED_SPACES],
                tenant_id=TENANT.id,
            )
        ],
    }
)
ORG_ADMIN = TEST_USER.model_copy(update={"tenant": TENANT})

LEVELS = {
    level: SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=TENANT.id,
        security_level=level,
        security_enabled=True,
    )
    for level in (1, 2, 3)
}


@pytest.fixture
def actor():
    return MagicMock()


def _service(actor: MagicMock, user, space_level: int | None) -> SpaceService:
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor

    space = SpaceFactory.create_space(
        name="Shared", tenant_id=TENANT.id, tenant_space_id=uuid4()
    )
    space.id = uuid4()
    space.security_classification = LEVELS.get(space_level)
    repo = AsyncMock()
    repo.one.return_value = space

    classifications = AsyncMock()
    classifications.get_security_classification.side_effect = lambda id: next(
        c for c in LEVELS.values() if c.id == id
    )
    return SpaceService(
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        embedding_model_crud_service=AsyncMock(),
        factory=MagicMock(),
        user_repo=AsyncMock(),
        user=user,
        actor_manager=actor_manager,
        completion_model_service=AsyncMock(),
        transcription_model_service=AsyncMock(),
        security_classification_service=classifications,
        icon_repo=AsyncMock(),
        user_groups_repo=AsyncMock(),
    )


def _with_floor(monkeypatch, level: int | None) -> AsyncMock:
    floor_for = AsyncMock(return_value=LEVELS.get(level))
    monkeypatch.setattr(space_service, "security_floor_for", floor_for)
    return floor_for


async def _set_level(service: SpaceService, level: int | None):
    await service.update_space(
        uuid4(),
        security_classification=ModelId(id=LEVELS[level].id) if level else None,
    )


def _stored_level_id(service: SpaceService):
    return service.repo.update_settings.await_args.args[1].security_classification_id


async def test_administrator_may_raise_the_level(actor, monkeypatch):
    _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=2)

    await _set_level(service, 3)

    assert _stored_level_id(service) == LEVELS[3].id


async def test_administrator_may_lower_the_level_to_their_own(actor, monkeypatch):
    _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=3)

    await _set_level(service, 2)

    assert _stored_level_id(service) == LEVELS[2].id


async def test_administrator_may_not_lower_the_level_below_their_own(
    actor, monkeypatch
):
    _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=3)

    with pytest.raises(UnauthorizedException, match="below your own security level"):
        await _set_level(service, 1)

    service.repo.update_settings.assert_not_awaited()


async def test_administrator_with_a_level_may_not_remove_the_classification(
    actor, monkeypatch
):
    _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=3)

    with pytest.raises(UnauthorizedException, match="below your own security level"):
        await _set_level(service, None)

    service.repo.update_settings.assert_not_awaited()


async def test_resending_a_level_below_the_floor_is_not_checked(actor, monkeypatch):
    floor_for = _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=1)

    await _set_level(service, 1)

    floor_for.assert_not_awaited()
    assert _stored_level_id(service) == LEVELS[1].id


async def test_a_space_below_the_floor_can_still_be_renamed(actor, monkeypatch):
    floor_for = _with_floor(monkeypatch, 2)
    service = _service(actor, MEMBER, space_level=1)

    await service.update_space(uuid4(), name="Renamed")

    floor_for.assert_not_awaited()
    service.repo.update_settings.assert_awaited_once()


@pytest.mark.parametrize("new_level", [1, None])
async def test_administrator_without_a_level_may_lower_freely(
    actor, monkeypatch, new_level
):
    _with_floor(monkeypatch, None)
    service = _service(actor, MEMBER, space_level=3)

    await _set_level(service, new_level)

    assert _stored_level_id(service) == (LEVELS[new_level].id if new_level else None)


@pytest.mark.parametrize("new_level", [1, None])
async def test_organisation_administrator_is_exempt(actor, monkeypatch, new_level):
    _with_floor(monkeypatch, 2)
    service = _service(actor, ORG_ADMIN, space_level=3)

    await _set_level(service, new_level)

    assert _stored_level_id(service) == (LEVELS[new_level].id if new_level else None)


async def test_editor_or_viewer_cannot_change_the_level_at_all(actor, monkeypatch):
    _with_floor(monkeypatch, None)
    actor.can_edit_space.return_value = False
    service = _service(actor, MEMBER, space_level=2)

    with pytest.raises(UnauthorizedException):
        await _set_level(service, 3)

    service.repo.update_settings.assert_not_awaited()
