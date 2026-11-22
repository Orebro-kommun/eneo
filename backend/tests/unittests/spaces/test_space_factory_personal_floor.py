"""A personal space's floor: its lists follow it, a shared space ignores it."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space_factory import SpaceFactory


@pytest.fixture
def factory():
    return SpaceFactory(MagicMock(), MagicMock())


def _classification(level: int, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=uuid4(),
        security_level=level,
        security_enabled=enabled,
    )


def _model(classification: SecurityClassification | None) -> MagicMock:
    model = MagicMock()
    model.id = uuid4()
    model.is_deprecated = False
    model.security_classification = classification
    return model


def _server(classification: SecurityClassification | None) -> MagicMock:
    server = MagicMock()
    server.id = uuid4()
    server.purpose = "general"
    server.effective_security_classification = classification
    return server


def _space_in_db(personal: bool = True) -> MagicMock:
    space_in_db = MagicMock()
    space_in_db.id = uuid4()
    space_in_db.tenant_id = uuid4()
    space_in_db.tenant_space_id = None
    space_in_db.user_id = uuid4() if personal else None
    space_in_db.members = []
    space_in_db.group_members = []
    space_in_db.capabilities = []
    space_in_db.completion_models_mapping = []
    space_in_db.transcription_models_mapping = []
    space_in_db.embedding_models_mapping = []
    space_in_db.mcp_servers_mapping = []
    space_in_db.integration_knowledge_list = []
    return space_in_db


def _personal_space(factory, floor, **lists):
    return factory.create_space_from_db(
        space_in_db=_space_in_db(), user=MagicMock(), floor=floor, **lists
    )


def test_personal_space_keeps_only_completion_models_that_meet_the_floor(factory):
    below, at_floor, above = (_model(_classification(level)) for level in (1, 2, 3))

    space = _personal_space(
        factory, _classification(2), completion_models=[below, at_floor, above]
    )

    assert [m.id for m in space.completion_models] == [at_floor.id, above.id]


def test_personal_space_drops_unclassified_models_when_it_has_a_floor(factory):
    unclassified = _model(None)
    classified = _model(_classification(1))

    space = _personal_space(
        factory, _classification(0), completion_models=[unclassified, classified]
    )

    assert [m.id for m in space.completion_models] == [classified.id]


def test_floor_applies_to_every_model_type_and_mcp_servers(factory):
    low, high = _classification(1), _classification(2)

    space = _personal_space(
        factory,
        _classification(2),
        embedding_models=[_model(low), _model(high)],
        transcription_models=[_model(low), _model(high)],
        mcp_servers=[_server(low), _server(high), _server(None)],
    )

    assert [m.security_classification for m in space.embedding_models] == [high]
    assert [m.security_classification for m in space.transcription_models] == [high]
    assert [s.effective_security_classification for s in space.mcp_servers] == [high]


def test_personal_space_carries_its_floor_as_its_classification(factory):
    floor = _classification(2)

    space = _personal_space(factory, floor)

    assert space.security_classification is floor


def test_personal_space_without_a_floor_keeps_every_model(factory):
    models = [_model(None), _model(_classification(0)), _model(_classification(5))]
    servers = [_server(None), _server(_classification(0))]

    space = _personal_space(
        factory, None, completion_models=models, mcp_servers=servers
    )

    assert [m.id for m in space.completion_models] == [m.id for m in models]
    assert [s.id for s in space.mcp_servers] == [s.id for s in servers]
    assert space.security_classification is None


def test_floor_does_nothing_while_classification_is_disabled(factory):
    models = [_model(None), _model(_classification(0))]

    space = _personal_space(
        factory, _classification(3, enabled=False), completion_models=models
    )

    assert [m.id for m in space.completion_models] == [m.id for m in models]


def test_shared_space_ignores_a_floor(factory):
    model = _model(None)
    space_in_db = _space_in_db(personal=False)
    space_in_db.completion_models_mapping = [MagicMock(completion_model_id=model.id)]

    space = factory.create_space_from_db(
        space_in_db=space_in_db,
        user=MagicMock(),
        floor=_classification(2),
        completion_models=[model],
    )

    assert [m.id for m in space.completion_models] == [model.id]
    assert space.security_classification is None
