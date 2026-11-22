"""The personal default assistant is moved off a model below its owner's floor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space_init_service import SpaceInitService


def _classification(level: int, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=uuid4(),
        security_level=level,
        security_enabled=enabled,
    )


LOW = _classification(1)
HIGH = _classification(2)


def _model(classification: SecurityClassification | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        can_access=True,
        deleted_at=None,
        migrated_to_model_id=None,
        security_classification=classification,
    )


def _service(*, current, floor, space_models, effective_config=None):
    """`space_models` is what the space offers: already cut by the floor."""
    assistant = SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        is_default=True,
        completion_model=current,
        update=MagicMock(),
    )
    space = SimpleNamespace(
        id=uuid4(),
        default_assistant=assistant,
        default_assistant_load_failed=False,
        completion_models=space_models,
        security_classification=floor,
        get_default_completion_model=MagicMock(
            return_value=next(iter(space_models), None)
        ),
    )
    effective_config_service = None
    if effective_config is not None:
        effective_config_service = MagicMock()
        effective_config_service.resolve_for = AsyncMock(return_value=effective_config)
    init_service = SpaceInitService(
        user=MagicMock(),
        space_service=MagicMock(get_personal_space=AsyncMock(return_value=space)),
        assistant_service=MagicMock(),
        space_repo=MagicMock(),
        assistant_repo=MagicMock(apply_update=AsyncMock()),
        effective_config_service=effective_config_service,
    )
    return init_service, assistant


async def test_a_model_below_the_floor_is_replaced_and_the_repair_is_stored():
    low, high = _model(LOW), _model(HIGH)
    init_service, assistant = _service(current=low, floor=HIGH, space_models=[high])

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is high
    args = init_service.assistant_repo.apply_update.await_args.args
    assert args[:2] == (assistant.id, assistant.space_id)
    assert args[2].completion_model_id == high.id
    assert args[2].completion_model_kwargs == ModelKwargs()


async def test_an_unclassified_model_is_below_every_floor():
    unclassified, high = _model(None), _model(HIGH)
    init_service, assistant = _service(
        current=unclassified, floor=LOW, space_models=[high]
    )

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is high


async def test_a_model_that_meets_the_floor_is_kept():
    high, other = _model(HIGH), _model(HIGH)
    init_service, assistant = _service(
        current=high, floor=LOW, space_models=[other, high]
    )

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_without_a_floor_an_unclassified_model_is_kept():
    unclassified, other = _model(None), _model(HIGH)
    init_service, assistant = _service(
        current=unclassified, floor=None, space_models=[other, unclassified]
    )

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_a_disabled_classification_moves_nothing():
    low, high = _model(LOW), _model(HIGH)
    init_service, assistant = _service(
        current=low, floor=_classification(2, enabled=False), space_models=[high, low]
    )

    await init_service.get_personal_space()

    assistant.update.assert_not_called()


async def test_when_no_model_meets_the_floor_the_assistant_is_left_alone():
    low = _model(LOW)
    init_service, assistant = _service(current=low, floor=HIGH, space_models=[])

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_an_enforced_policy_is_resolved_with_the_floor_and_picks_the_fallback():
    low, high, policy_model = _model(LOW), _model(HIGH), _model(HIGH)
    effective_config = SimpleNamespace(
        models_enforced=True,
        available_models=[policy_model],
        policy_default_model=None,
        locked_model=policy_model,
    )
    init_service, assistant = _service(
        current=low, floor=HIGH, space_models=[high], effective_config=effective_config
    )

    await init_service.get_personal_space()

    init_service.effective_config_service.resolve_for.assert_awaited_once_with(
        assistant, space_is_personal=True, floor=HIGH
    )
    assert assistant.update.call_args.kwargs["completion_model"] is policy_model
