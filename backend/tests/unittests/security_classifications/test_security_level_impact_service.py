from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.security_classifications.application.security_classification_service import (
    SecurityClassificationService,
)
from eneo.security_classifications.application.security_level_impact_service import (
    SecurityLevelImpactService,
)


def _level(security_level: int) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), security_level=security_level)


def _model(level: int | None, can_access: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        can_access=can_access,
        security_classification=None if level is None else _level(level),
    )


def _service(models, permissions=(Permission.ADMIN,)) -> SecurityLevelImpactService:
    crud = AsyncMock()
    crud.get_completion_models.return_value = models
    crud.get_embedding_models.return_value = models
    crud.get_transcription_models.return_value = models
    return SecurityLevelImpactService(
        user=MagicMock(tenant_id=uuid4(), permissions=set(permissions)),
        repo=AsyncMock(),
        completion_model_crud_service=crud,
        embedding_model_crud_service=crud,
        transcription_model_crud_service=crud,
    )


MODELS = [_model(1), _model(2), _model(3), _model(None), _model(3, can_access=False)]


async def test_only_available_models_at_or_above_the_level_are_usable():
    assert await _service(MODELS).usable_completion_models(_level(2)) == 2


async def test_without_a_level_every_available_model_is_usable():
    assert await _service(MODELS).usable_completion_models(None) == 4


async def test_the_preview_joins_the_counts_with_the_usable_models():
    service = _service(MODELS)
    level = _level(3)
    group_id = uuid4()
    service.repo.one.return_value = level
    service.repo.count_level_impact.return_value = {
        "affected_users": 4,
        "assistants": 3,
        "apps": 2,
        "services": 1,
        "knowledge_sources": 0,
    }

    impact = await service.preview(level.id, group_id)

    service.repo.count_level_impact.assert_awaited_once_with(3, group_id)
    assert (impact.affected_users, impact.assistants, impact.apps) == (4, 3, 2)
    assert (
        impact.completion_models,
        impact.embedding_models,
        impact.transcription_models,
    ) == (1, 1, 1)


async def test_clearing_is_previewed_without_a_lookup():
    service = _service(MODELS)
    service.repo.count_level_impact.return_value = dict.fromkeys(
        ("affected_users", "assistants", "apps", "services", "knowledge_sources"), 0
    )

    impact = await service.preview(None, None)

    service.repo.one.assert_not_awaited()
    service.repo.count_level_impact.assert_awaited_once_with(None, None)
    assert impact.completion_models == 4


async def test_the_preview_refuses_a_user_without_admin_permission():
    with pytest.raises(UnauthorizedException):
        await _service(MODELS, permissions=()).preview(None, None)


async def test_a_default_no_completion_model_meets_is_refused():
    impact_service = AsyncMock()
    impact_service.usable_completion_models.return_value = 0
    tenant_service = AsyncMock()
    service = SecurityClassificationService(
        MagicMock(tenant_id=uuid4(), permissions={Permission.ADMIN}),
        AsyncMock(),
        tenant_service,
        impact_service,
    )

    with pytest.raises(BadRequestException):
        await service.set_default_user_classification(uuid4())

    tenant_service.set_default_user_security_classification.assert_not_awaited()
