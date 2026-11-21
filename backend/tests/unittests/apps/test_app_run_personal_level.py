"""A personal app below its owner's level is refused with the reason."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.apps.apps.app_service import AppService
from eneo.main.exceptions import SecurityClassificationMismatchException


async def test_the_refusal_names_the_security_level():
    space = MagicMock()
    space.can_run_app.return_value = False
    space.check_personal_level.side_effect = SecurityClassificationMismatchException()
    service = AppService(
        user=MagicMock(),
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        factory=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        file_service=AsyncMock(),
        prompt_service=AsyncMock(),
        transcriber=AsyncMock(),
        app_template_service=AsyncMock(),
        actor_manager=MagicMock(),
        completion_service=AsyncMock(),
        icon_repo=AsyncMock(),
        skill_service=AsyncMock(),
    )
    service.space_repo.get_space_by_app.return_value = space
    app = space.get_app.return_value

    with pytest.raises(SecurityClassificationMismatchException):
        await service._get_runnable_app(uuid4())

    space.check_personal_level.assert_called_once_with(
        app.completion_model, app.transcription_model
    )
