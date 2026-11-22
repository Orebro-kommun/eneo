"""Setting the organisation's default level: existence check and audit entry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.security_classifications.application.security_classification_service import (
    SecurityClassificationService,
)
from eneo.security_classifications.presentation.security_classification_models import (
    DefaultUserClassificationRequest,
)
from eneo.security_classifications.presentation.security_classification_router import (
    set_default_user_classification,
)


def _service(permissions=(Permission.ADMIN,)):
    user = MagicMock(tenant_id=uuid4(), permissions=set(permissions))
    repo = AsyncMock()
    tenant_service = AsyncMock()
    return SecurityClassificationService(user, repo, tenant_service, AsyncMock())


async def test_service_stores_an_existing_classification_as_default():
    service = _service()
    classification_id = uuid4()

    await service.set_default_user_classification(classification_id)

    service.repo.one.assert_awaited_once_with(id=classification_id)
    service.tenant_service.set_default_user_security_classification.assert_awaited_once_with(
        tenant_id=service.user.tenant_id, classification_id=classification_id
    )


async def test_service_refuses_a_level_no_completion_model_meets():
    service = _service()
    service.impact_service.usable_completion_models.return_value = 0

    with pytest.raises(BadRequestException):
        await service.set_default_user_classification(uuid4())

    service.tenant_service.set_default_user_security_classification.assert_not_awaited()


async def test_service_refuses_an_unknown_classification():
    service = _service()
    service.repo.one.side_effect = NotFoundException("missing")

    with pytest.raises(NotFoundException):
        await service.set_default_user_classification(uuid4())

    service.tenant_service.set_default_user_security_classification.assert_not_awaited()


async def test_service_clears_the_default_without_a_lookup():
    service = _service()

    await service.set_default_user_classification(None)

    service.repo.one.assert_not_awaited()
    service.tenant_service.set_default_user_security_classification.assert_awaited_once_with(
        tenant_id=service.user.tenant_id, classification_id=None
    )


async def test_service_refuses_a_user_without_admin_permission():
    service = _service(permissions=())

    with pytest.raises(UnauthorizedException):
        await service.set_default_user_classification(None)

    service.tenant_service.set_default_user_security_classification.assert_not_awaited()


async def test_router_audits_the_old_and_the_new_level():
    old_id, new_id, tenant_id = uuid4(), uuid4(), uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        username="admin",
        email="admin@example.com",
        tenant_id=tenant_id,
        tenant=SimpleNamespace(default_user_security_classification_id=old_id),
    )
    container = MagicMock()
    container.user.return_value = user
    service = container.security_classification_service.return_value
    service.set_default_user_classification = AsyncMock(
        return_value=SimpleNamespace(
            id=tenant_id, name="org", default_user_security_classification_id=new_id
        )
    )
    audit_service = container.audit_service.return_value
    audit_service.log_async = AsyncMock()

    response = await set_default_user_classification(
        request=DefaultUserClassificationRequest(
            security_classification=ModelId(id=new_id)
        ),
        container=container,
    )

    assert response.default_user_security_classification_id == new_id
    service.set_default_user_classification.assert_awaited_once_with(new_id)
    logged = audit_service.log_async.await_args.kwargs
    assert logged["action"] == ActionType.TENANT_SETTINGS_UPDATED
    assert logged["entity_type"] == EntityType.TENANT_SETTINGS
    assert logged["entity_id"] == tenant_id
    assert logged["metadata"]["changes"] == {
        "default_user_security_classification_id": {
            "old": str(old_id),
            "new": str(new_id),
        }
    }
