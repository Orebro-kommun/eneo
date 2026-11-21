"""A new shared space starts at its creator's security level."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces import space_service
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_service import SpaceService
from tests.fixtures import TEST_USER


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=TEST_USER.tenant_id,
        security_level=level,
        security_enabled=True,
    )


def _model(classification: SecurityClassification | None, day: int = 1) -> MagicMock:
    model = MagicMock()
    model.id = uuid4()
    model.can_access = True
    model.created_at = datetime(2024, 1, day)
    model.security_classification = classification
    return model


def _server_row(classification: SecurityClassification | None) -> SimpleNamespace:
    """An MCP server row as the query returns it, with its classification row."""
    classification_row = classification and SimpleNamespace(
        id=classification.id,
        tenant_id=classification.tenant_id,
        name=classification.name,
        description=None,
        security_level=classification.security_level,
        created_at=None,
        updated_at=None,
        tenant=SimpleNamespace(security_enabled=True),
    )
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=TEST_USER.tenant_id,
        name="server",
        description=None,
        http_url="https://example.com/mcp",
        http_auth_type="none",
        http_auth_config_schema=None,
        purpose="general",
        is_enabled=True,
        env_vars=None,
        tags=None,
        icon_url=None,
        documentation_url=None,
        created_at=None,
        updated_at=None,
        security_classification=classification_row,
    )


@pytest.fixture
def service():
    repo = AsyncMock()
    repo.session = MagicMock()
    repo.session.execute = AsyncMock()
    service = SpaceService(
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        embedding_model_crud_service=AsyncMock(),
        factory=SpaceFactory(MagicMock(), MagicMock()),
        user_repo=AsyncMock(),
        user=TEST_USER,
        actor_manager=MagicMock(),
        completion_model_service=AsyncMock(),
        transcription_model_service=AsyncMock(),
        security_classification_service=AsyncMock(),
        icon_repo=AsyncMock(),
        user_groups_repo=AsyncMock(),
    )
    service.get_or_create_tenant_space = AsyncMock(return_value=MagicMock(id=uuid4()))
    return service


def _offer(
    service: SpaceService,
    *,
    completion=(),
    embedding=(),
    transcription=None,
    servers=(),
) -> None:
    service.completion_model_service.get_available_completion_models.return_value = (
        list(completion)
    )
    service.embedding_model_crud_service.get_embedding_models.return_value = list(
        embedding
    )
    service.transcription_model_service.get_default_model.return_value = transcription
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(servers)
    service.repo.session.execute.return_value = result


def _with_floor(monkeypatch, floor: SecurityClassification | None) -> None:
    monkeypatch.setattr(
        space_service, "security_floor_for", AsyncMock(return_value=floor)
    )


async def _created(service: SpaceService):
    await service.create_space("New space")
    return service.repo.add.await_args.args[0]


async def test_space_gets_the_creators_level(service, monkeypatch):
    floor = _classification(2)
    _with_floor(monkeypatch, floor)
    _offer(service)

    space = await _created(service)

    assert space.security_classification is floor


async def test_only_completion_models_that_meet_the_level_are_enabled(
    service, monkeypatch
):
    _with_floor(monkeypatch, _classification(2))
    below, at_level, above, unclassified = (
        _model(_classification(1)),
        _model(_classification(2)),
        _model(_classification(3)),
        _model(None),
    )
    _offer(service, completion=[below, at_level, above, unclassified])

    space = await _created(service)

    assert space.completion_models == [at_level, above]


async def test_the_latest_embedding_model_that_meets_the_level_is_enabled(
    service, monkeypatch
):
    _with_floor(monkeypatch, _classification(2))
    newest_below = _model(_classification(1), day=3)
    older_at_level = _model(_classification(2), day=2)
    oldest_at_level = _model(_classification(2), day=1)
    _offer(service, embedding=[oldest_at_level, newest_below, older_at_level])

    space = await _created(service)

    assert space.embedding_models == [older_at_level]


async def test_a_default_transcription_model_below_the_level_is_left_out(
    service, monkeypatch
):
    _with_floor(monkeypatch, _classification(2))
    _offer(service, transcription=_model(_classification(1)))

    space = await _created(service)

    assert space.transcription_models == []


async def test_only_mcp_servers_that_meet_the_level_are_enabled(service, monkeypatch):
    _with_floor(monkeypatch, _classification(2))
    below, at_level, unclassified = (
        _server_row(_classification(1)),
        _server_row(_classification(2)),
        _server_row(None),
    )
    _offer(service, servers=[below, at_level, unclassified])

    space = await _created(service)

    assert [server.id for server in space.mcp_servers] == [at_level.id]


async def test_without_a_level_the_space_is_created_as_before(service, monkeypatch):
    _with_floor(monkeypatch, None)
    completion = [_model(_classification(1)), _model(None)]
    newest, older = _model(None, day=2), _model(_classification(1), day=1)
    transcription = _model(None)
    servers = [_server_row(_classification(1)), _server_row(None)]
    _offer(
        service,
        completion=completion,
        embedding=[older, newest],
        transcription=transcription,
        servers=servers,
    )

    space = await _created(service)

    assert space.security_classification is None
    assert space.completion_models == completion
    assert space.embedding_models == [newest]
    assert space.transcription_models == [transcription]
    assert [server.id for server in space.mcp_servers] == [s.id for s in servers]
