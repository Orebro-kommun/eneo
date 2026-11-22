"""A personal assistant, app, service or knowledge source keeps its stored model,
but cannot be used while that model is below the owner's floor."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import SecurityClassificationMismatchException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space_factory import SpaceFactory


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=uuid4(),
        security_level=level,
        security_enabled=True,
    )


def _model(classification: SecurityClassification | None) -> MagicMock:
    model = MagicMock()
    model.id = uuid4()
    model.is_deprecated = False
    model.can_access = True
    model.security_classification = classification
    return model


def _space_in_db() -> MagicMock:
    space_in_db = MagicMock()
    space_in_db.id = uuid4()
    space_in_db.tenant_id = uuid4()
    space_in_db.tenant_space_id = None
    space_in_db.user_id = uuid4()
    space_in_db.members = []
    space_in_db.group_members = []
    space_in_db.capabilities = []
    space_in_db.completion_models_mapping = []
    space_in_db.transcription_models_mapping = []
    space_in_db.embedding_models_mapping = []
    space_in_db.mcp_servers_mapping = []
    space_in_db.integration_knowledge_list = []
    return space_in_db


LOW = _classification(1)
HIGH = _classification(3)


@pytest.fixture
def models():
    return {
        "low_chat": _model(LOW),
        "high_chat": _model(HIGH),
        "low_embedding": _model(LOW),
        "high_embedding": _model(HIGH),
        "low_transcription": _model(LOW),
        "high_transcription": _model(HIGH),
    }


@pytest.fixture
def space(models):
    return SpaceFactory(MagicMock(), MagicMock()).create_space_from_db(
        space_in_db=_space_in_db(),
        user=MagicMock(),
        floor=HIGH,
        completion_models=[models["low_chat"], models["high_chat"]],
        embedding_models=[models["low_embedding"], models["high_embedding"]],
        transcription_models=[
            models["low_transcription"],
            models["high_transcription"],
        ],
    )


def _assistant(completion_model: MagicMock) -> MagicMock:
    assistant = MagicMock()
    assistant.completion_model = completion_model
    assistant.collections = []
    assistant.websites = []
    assistant.integration_knowledge_list = []
    return assistant


def test_an_assistant_whose_model_is_below_the_floor_cannot_be_asked(space, models):
    with pytest.raises(SecurityClassificationMismatchException):
        space.can_ask_assistant(_assistant(models["low_chat"]))


def test_an_assistant_whose_model_meets_the_floor_can_be_asked(space, models):
    space.can_ask_assistant(_assistant(models["high_chat"]))


def test_an_app_whose_model_is_below_the_floor_cannot_run(space, models):
    app = MagicMock()
    app.completion_model = models["low_chat"]
    app.transcription_model = models["high_transcription"]

    assert space.can_run_app(app) is False


def test_an_app_whose_transcription_model_is_below_the_floor_cannot_run(space, models):
    app = MagicMock()
    app.completion_model = models["high_chat"]
    app.transcription_model = models["low_transcription"]

    assert space.can_run_app(app) is False


def test_an_app_whose_models_meet_the_floor_can_run(space, models):
    app = MagicMock()
    app.completion_model = models["high_chat"]
    app.transcription_model = models["high_transcription"]

    assert space.can_run_app(app) is True


def test_a_service_whose_model_is_below_the_floor_cannot_be_used(space, models):
    service = MagicMock()
    service.completion_model = models["low_chat"]

    assert space.can_use_service(service) is False


def test_a_service_whose_model_meets_the_floor_can_be_used(space, models):
    service = MagicMock()
    service.completion_model = models["high_chat"]

    assert space.can_use_service(service) is True


def test_knowledge_with_an_embedding_model_below_the_floor_cannot_be_used(
    space, models
):
    knowledge = MagicMock()
    knowledge.embedding_model = models["low_embedding"]

    assert space.can_use_knowledge([knowledge]) is False


def test_knowledge_with_an_embedding_model_that_meets_the_floor_can_be_used(
    space, models
):
    knowledge = MagicMock()
    knowledge.embedding_model = models["high_embedding"]

    assert space.can_use_knowledge([knowledge]) is True
