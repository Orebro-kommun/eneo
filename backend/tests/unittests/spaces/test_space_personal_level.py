"""A personal space refuses a model below its owner's level and says why."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    ModelNotAvailableException,
    SecurityClassificationMismatchException,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


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


def _model(classification: SecurityClassification | None) -> MagicMock:
    return MagicMock(
        id=uuid4(), can_access=True, security_classification=classification
    )


def _space(*, personal: bool, floor: SecurityClassification | None, models=()) -> Space:
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=None,
        user_id=uuid4() if personal else None,
        name="space",
        description=None,
        embedding_models=[],
        completion_models=list(models),
        transcription_models=[],
        mcp_servers=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=floor,
    )


def _assistant(model: MagicMock) -> MagicMock:
    return MagicMock(
        completion_model=model,
        collections=[],
        websites=[],
        integration_knowledge_list=[],
    )


@pytest.mark.parametrize("classification", [LOW, None])
def test_an_assistant_with_a_model_below_the_owners_level_is_refused_with_the_reason(
    classification,
):
    # The floor-filtered list of a personal space never holds such a model.
    space = _space(personal=True, floor=HIGH, models=[_model(HIGH)])

    with pytest.raises(
        SecurityClassificationMismatchException, match="your security level"
    ):
        space.can_ask_assistant(_assistant(_model(classification)))


def test_an_assistant_with_a_model_that_meets_the_owners_level_may_be_asked():
    model = _model(HIGH)
    space = _space(personal=True, floor=LOW, models=[model])

    space.can_ask_assistant(_assistant(model))


def test_a_model_missing_for_another_reason_is_still_reported_as_unavailable():
    space = _space(personal=True, floor=LOW, models=[])

    with pytest.raises(ModelNotAvailableException):
        space.can_ask_assistant(_assistant(_model(HIGH)))


def test_without_a_level_a_personal_space_reports_a_missing_model_as_before():
    space = _space(personal=True, floor=None, models=[])

    with pytest.raises(ModelNotAvailableException):
        space.can_ask_assistant(_assistant(_model(None)))


def test_a_disabled_classification_refuses_nothing():
    space = _space(personal=True, floor=_classification(2, enabled=False))

    space.check_personal_level(_model(None), None)


def test_a_shared_space_keeps_its_own_refusal():
    space = _space(personal=False, floor=HIGH, models=[])

    with pytest.raises(ModelNotAvailableException):
        space.can_ask_assistant(_assistant(_model(LOW)))


def test_an_app_or_service_model_below_the_owners_level_is_refused_with_the_reason():
    space = _space(personal=True, floor=HIGH)

    with pytest.raises(
        SecurityClassificationMismatchException, match="your security level"
    ):
        space.check_personal_level(_model(HIGH), _model(LOW))
