"""A user's effective security level, where it comes from, and the floor rule."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.security_classifications.domain.effective_level import (
    EffectiveSecurityLevel,
    effective_security_level,
    meets_security_floor,
    security_floor_for,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)


def _user(default_id=None, security_enabled=True):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant=SimpleNamespace(
            security_enabled=security_enabled,
            default_user_security_classification_id=default_id,
        ),
    )


def _classification(level: int, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        name=f"level {level}",
        tenant_id=uuid4(),
        security_level=level,
        security_enabled=enabled,
    )


def _row(level: int, enabled: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"level {level}",
        description=None,
        security_level=level,
        created_at=None,
        updated_at=None,
        tenant=SimpleNamespace(security_enabled=enabled),
    )


@pytest.fixture
def session():
    session = MagicMock()
    session.info = {}
    session.scalar = AsyncMock()
    return session


def test_user_without_a_default_has_no_level():
    assert effective_security_level(_user()) == EffectiveSecurityLevel(  # type: ignore[arg-type]
        security_classification_id=None, source="none"
    )


def test_user_gets_the_organisations_default():
    default_id = uuid4()

    level = effective_security_level(_user(default_id))  # type: ignore[arg-type]

    assert level == EffectiveSecurityLevel(
        security_classification_id=default_id, source="default"
    )
    assert level.user_group_id is None


def test_no_level_applies_while_classification_is_disabled():
    level = effective_security_level(_user(uuid4(), security_enabled=False))  # type: ignore[arg-type]

    assert level == EffectiveSecurityLevel(
        security_classification_id=None, source="none"
    )


def test_everything_meets_a_missing_floor():
    assert meets_security_floor(None, None)
    assert meets_security_floor(None, _classification(0))


def test_resource_meets_the_floor_from_the_same_level_and_up():
    floor = _classification(2)

    assert not meets_security_floor(floor, _classification(1))
    assert meets_security_floor(floor, _classification(2))
    assert meets_security_floor(floor, _classification(3))


def test_unclassified_resource_meets_no_floor():
    assert not meets_security_floor(_classification(0), None)


def test_disabled_floor_lets_everything_through():
    floor = _classification(2, enabled=False)

    assert meets_security_floor(floor, None)
    assert meets_security_floor(floor, _classification(1))


async def test_floor_is_not_looked_up_when_no_level_is_set(session):
    assert await security_floor_for(session, _user()) is None  # type: ignore[arg-type]

    session.scalar.assert_not_awaited()


async def test_floor_is_not_looked_up_while_classification_is_disabled(session):
    user = _user(uuid4(), security_enabled=False)

    assert await security_floor_for(session, user) is None  # type: ignore[arg-type]

    session.scalar.assert_not_awaited()


async def test_floor_is_the_classification_of_the_effective_level(session):
    default_id = uuid4()
    row = _row(2)
    session.scalar.return_value = row

    floor = await security_floor_for(session, _user(default_id))  # type: ignore[arg-type]

    assert floor is not None
    assert floor.id == row.id
    assert floor.security_level == 2
    assert default_id in session.scalar.await_args.args[0].compile().params.values()


async def test_floor_is_looked_up_once_per_session(session):
    user = _user(uuid4())
    session.scalar.return_value = _row(2)

    first = await security_floor_for(session, user)  # type: ignore[arg-type]
    second = await security_floor_for(session, user)  # type: ignore[arg-type]

    assert second is first
    assert session.scalar.await_count == 1
