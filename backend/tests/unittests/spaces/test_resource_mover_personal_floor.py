"""An assistant may not leave a personal space for a space below its owner's level."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.domain import resource_mover_service
from eneo.spaces.domain.resource_mover_service import ResourceMoverService
from tests.fixtures import TEST_TENANT, TEST_USER

TENANT = TEST_TENANT.model_copy(update={"security_enabled": True})
MEMBER = TEST_USER.model_copy(
    update={
        "tenant": TENANT,
        "roles": [
            RoleInDB(
                id=uuid4(),
                name="Member",
                permissions=[Permission.ASSISTANTS],
                tenant_id=TENANT.id,
            )
        ],
    }
)
ORG_ADMIN = TEST_USER.model_copy(update={"tenant": TENANT})


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=TENANT.id,
        security_level=level,
        security_enabled=True,
    )


def _space(*, personal: bool, level: int | None = None) -> MagicMock:
    space = MagicMock()
    space.id = uuid4()
    space.tenant_id = TENANT.id
    space.is_personal.return_value = personal
    space.security_classification = _classification(level) if level else None
    space.get_assistant.return_value = MagicMock(
        is_default=False, completion_model=None
    )
    return space


def _mover(source: MagicMock, target: MagicMock, user=MEMBER) -> ResourceMoverService:
    space_service = AsyncMock()
    space_service.get_space_by_assistant.return_value = source
    space_service.get_space.side_effect = lambda space_id: (
        source if space_id == source.id else target
    )
    skill_repo = AsyncMock()
    skill_repo.lock_assistant_space_for_update.return_value = source.id
    skill_repo.has_assistant_bindings.return_value = False
    widget_repo = AsyncMock()
    widget_repo.list_by_target.return_value = []
    return ResourceMoverService(
        user=user,
        space_service=space_service,
        space_repo=AsyncMock(),
        actor_manager=MagicMock(),
        skill_repo=skill_repo,
        widget_repo=widget_repo,
        assistant_repo=AsyncMock(),
    )


def _with_floor(monkeypatch, level: int | None) -> None:
    monkeypatch.setattr(
        resource_mover_service,
        "security_floor_for",
        AsyncMock(return_value=_classification(level) if level else None),
    )


async def _move(service: ResourceMoverService, target: MagicMock) -> None:
    await service.move_assistant_to_space(assistant_id=uuid4(), space_id=target.id)


@pytest.mark.parametrize("target_level", [1, None])
async def test_move_from_personal_space_to_a_lower_space_is_refused(
    monkeypatch, target_level
):
    _with_floor(monkeypatch, 2)
    source = _space(personal=True, level=2)
    target = _space(personal=False, level=target_level)
    service = _mover(source, target)

    with pytest.raises(UnauthorizedException, match="below your security level"):
        await _move(service, target)

    target.add_assistant.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


@pytest.mark.parametrize("target_level", [2, 3])
async def test_move_from_personal_space_to_a_space_at_or_above_the_level_is_allowed(
    monkeypatch, target_level
):
    _with_floor(monkeypatch, 2)
    source = _space(personal=True, level=2)
    target = _space(personal=False, level=target_level)
    service = _mover(source, target)

    await _move(service, target)

    service.assistant_repo.move.assert_awaited_once()


async def test_move_between_shared_spaces_ignores_the_users_level(monkeypatch):
    _with_floor(monkeypatch, 2)
    source = _space(personal=False, level=2)
    target = _space(personal=False, level=None)
    service = _mover(source, target)

    await _move(service, target)

    service.assistant_repo.move.assert_awaited_once()


async def test_user_without_a_level_moves_out_of_the_personal_space_as_before(
    monkeypatch,
):
    _with_floor(monkeypatch, None)
    source = _space(personal=True)
    target = _space(personal=False, level=None)
    service = _mover(source, target)

    await _move(service, target)

    service.assistant_repo.move.assert_awaited_once()


async def test_organisation_administrator_is_exempt(monkeypatch):
    _with_floor(monkeypatch, 2)
    source = _space(personal=True, level=2)
    target = _space(personal=False, level=None)
    service = _mover(source, target, user=ORG_ADMIN)

    await _move(service, target)

    service.assistant_repo.move.assert_awaited_once()
