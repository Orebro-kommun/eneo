"""A personal service below its owner's level is refused with the reason."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import SecurityClassificationMismatchException
from eneo.services.service_service import ServiceService


async def test_the_refusal_names_the_security_level():
    space = MagicMock()
    space.can_use_service.return_value = False
    space.check_personal_level.side_effect = SecurityClassificationMismatchException()
    service = ServiceService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        question_repo=AsyncMock(),
        group_service=AsyncMock(),
        user=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
    )
    service.space_repo.get_space_by_service.return_value = space

    with pytest.raises(SecurityClassificationMismatchException):
        await service.get_runnable_service(uuid4())

    space.check_personal_level.assert_called_once_with(
        space.get_service.return_value.completion_model
    )
