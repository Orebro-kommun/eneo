"""A user's effective security level when user groups carry a level."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from eneo.security_classifications.domain.effective_level import (
    EffectiveSecurityLevel,
    effective_security_level,
)

_NONE = EffectiveSecurityLevel(security_classification_id=None, source="none")


def _group(level: int | None = None, state: str | None = None, id: UUID | None = None):
    classification = (
        None if level is None else SimpleNamespace(id=uuid4(), security_level=level)
    )
    return SimpleNamespace(
        id=id or uuid4(), state=state, security_classification=classification
    )


def _level(*groups, default_id=None, security_enabled=True) -> EffectiveSecurityLevel:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        user_groups=list(groups),
        tenant=SimpleNamespace(
            security_enabled=security_enabled,
            default_user_security_classification_id=default_id,
        ),
    )
    return effective_security_level(user)  # type: ignore[arg-type]


def _from_group(group) -> EffectiveSecurityLevel:
    return EffectiveSecurityLevel(
        security_classification_id=group.security_classification.id,
        source="group",
        user_group_id=group.id,
    )


def _from_default(default_id) -> EffectiveSecurityLevel:
    return EffectiveSecurityLevel(
        security_classification_id=default_id, source="default"
    )


def test_user_without_groups_and_default_has_no_level():
    assert _level() == _NONE


def test_user_gets_the_level_of_the_group():
    group = _group(1)

    assert _level(group) == _from_group(group)


def test_strictest_group_wins_whatever_the_order():
    low, high, middle = _group(1), _group(3), _group(2)

    assert _level(low, high, middle) == _from_group(high)
    assert _level(high, middle, low) == _from_group(high)


def test_groups_on_the_same_level_give_the_one_with_the_lowest_id():
    first = _group(2, id=UUID(int=1))
    second = _group(2, id=UUID(int=2))

    assert _level(first, second) == _from_group(first)
    assert _level(second, first) == _from_group(first)


def test_group_without_a_level_does_not_count():
    default_id = uuid4()

    assert _level(_group()) == _NONE
    assert _level(_group(), default_id=default_id) == _from_default(default_id)


def test_group_without_a_level_does_not_hide_one_that_has():
    group = _group(0)

    assert _level(_group(), group) == _from_group(group)


def test_deleted_group_does_not_count():
    default_id = uuid4()
    deleted = _group(3, state="deleted")
    live = _group(1)

    assert _level(deleted) == _NONE
    assert _level(deleted, live) == _from_group(live)
    assert _level(deleted, default_id=default_id) == _from_default(default_id)


def test_group_below_the_default_wins_over_the_default():
    # The default is a fallback, not a minimum: it is never compared.
    group = _group(0)

    assert _level(group, default_id=uuid4()) == _from_group(group)


def test_default_applies_when_there_are_no_groups():
    default_id = uuid4()

    assert _level(default_id=default_id) == _from_default(default_id)


def test_group_level_does_not_apply_while_classification_is_disabled():
    assert _level(_group(2), default_id=uuid4(), security_enabled=False) == _NONE
