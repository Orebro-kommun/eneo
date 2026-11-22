"""The paths around a question that pick their own model follow the owner's level."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.conversations.application.conversation_service import ConversationService
from eneo.group_chat.application.group_chat_service import GroupChatService
from eneo.main.exceptions import SecurityClassificationMismatchException
from tests.unittests.assistants.test_governance_policy_runtime import (
    _not_helper_history_repo,
    _not_helper_role_repo,
    _service_with_actor,
)

LOW_MODEL = SimpleNamespace(name="below the level")
HIGH_MODEL = SimpleNamespace(name="meets the level")


def _personal_space(**assistants) -> MagicMock:
    """A personal space whose owner's level only HIGH_MODEL meets."""

    def check(*models):
        if any(model is LOW_MODEL for model in models):
            raise SecurityClassificationMismatchException("below the level")

    space = MagicMock()
    space.is_personal.return_value = True
    space.check_personal_level.side_effect = check
    space.get_assistant.side_effect = lambda assistant_id: assistants[str(assistant_id)]
    return space


def _assistant(model) -> MagicMock:
    assistant = MagicMock()
    assistant.id = uuid4()
    assistant.is_default = False
    assistant.completion_model = model
    assistant.tool_assistants = []
    return assistant


async def test_a_mentioned_assistant_below_the_level_is_not_asked():
    mentioned = _assistant(LOW_MODEL)
    active = _assistant(HIGH_MODEL)
    active.tool_assistants = [mentioned]
    space = _personal_space(**{str(active.id): active, str(mentioned.id): mentioned})
    service = _service_with_actor(MagicMock())
    service.space_repo.get_space_by_assistant.return_value = space
    service.file_service.get_files_by_ids.return_value = []
    service.org_space_assistant_role_repo = _not_helper_role_repo()
    service.help_assistant_assignment_history_repo = _not_helper_history_repo()

    with pytest.raises(SecurityClassificationMismatchException):
        await service.ask(
            question="hello", assistant_id=active.id, tool_assistant_id=mentioned.id
        )

    mentioned.ask.assert_not_called()
    service.session_service.create_session_with_question_placeholder.assert_not_awaited()


async def test_a_group_chat_does_not_route_with_a_model_below_the_level():
    first = SimpleNamespace(assistant=_assistant(LOW_MODEL), user_description=None)
    group_chat = SimpleNamespace(assistants=[first], allow_mentions=False)
    space = _personal_space()
    space.get_group_chat.return_value = group_chat
    completion_service = MagicMock(get_response=AsyncMock())
    service = GroupChatService(
        user=MagicMock(),
        space_service=MagicMock(get_space_by_group_chat=AsyncMock(return_value=space)),
        group_chat_repo=AsyncMock(),
        space_repo=MagicMock(),
        actor_manager=MagicMock(),
        assistant_service=MagicMock(),
        session_service=MagicMock(),
        completion_service=completion_service,
        icon_repo=MagicMock(),
    )

    with pytest.raises(SecurityClassificationMismatchException):
        await service.ask_group_chat(question="hello", group_chat_id=uuid4())

    completion_service.get_response.assert_not_awaited()


async def test_a_title_is_not_written_by_a_model_below_the_level():
    assistant = _assistant(LOW_MODEL)
    space = _personal_space(**{str(assistant.id): assistant})
    completion_service = MagicMock(get_response=AsyncMock())
    service = ConversationService(
        assistant_service=AsyncMock(),
        group_chat_service=AsyncMock(),
        session_service=AsyncMock(
            get_session_by_uuid=AsyncMock(
                return_value=SimpleNamespace(assistant=assistant)
            )
        ),
        completion_service=completion_service,
        space_service=MagicMock(get_space_by_assistant=AsyncMock(return_value=space)),
        file_service=AsyncMock(),
    )

    with pytest.raises(SecurityClassificationMismatchException):
        await service.set_title_of_conversation(uuid4())

    completion_service.get_response.assert_not_awaited()
