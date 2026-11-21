"""The personal default assistant's policy is resolved with its owner's floor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.assistants.assistant_service import AssistantService
from eneo.spaces.api.space_router import _space_response
from tests.fixtures import TEST_USER


def _assistant_service(effective_config_service: AsyncMock) -> AssistantService:
    return AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        user=TEST_USER,
        auth_service=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(),
        actor_manager=MagicMock(),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=AsyncMock(),
        help_assistant_assignment_history_repo=AsyncMock(),
        skill_service=AsyncMock(),
        effective_config_service=effective_config_service,
    )


def _personal_space(floor: object) -> SimpleNamespace:
    assistant = SimpleNamespace(id=uuid4(), is_default=True)
    return SimpleNamespace(
        default_assistant=assistant,
        security_classification=floor,
        is_personal=lambda: True,
    )


async def test_the_assistant_service_resolves_the_policy_with_the_spaces_floor():
    floor = object()
    space = _personal_space(floor)
    effective_config_service = AsyncMock()
    service = _assistant_service(effective_config_service)

    resolved = await service._resolve_effective_config(
        space=space, assistant=space.default_assistant
    )

    effective_config_service.resolve_for.assert_awaited_once_with(
        space.default_assistant, space_is_personal=True, floor=floor
    )
    assert resolved is effective_config_service.resolve_for.return_value


async def test_the_space_response_resolves_the_policy_with_the_spaces_floor():
    floor = object()
    space = _personal_space(floor)
    effective_config_service = AsyncMock()
    container = MagicMock()
    container.effective_config_service.return_value = effective_config_service

    await _space_response(container, space)

    effective_config_service.resolve_for.assert_awaited_once_with(
        space.default_assistant, space_is_personal=True, floor=floor
    )
    container.space_assembler.return_value.from_space_to_model.assert_called_once_with(
        space,
        default_assistant_effective_config=(
            effective_config_service.resolve_for.return_value
        ),
    )


async def test_the_fleet_wide_fit_check_resolves_the_policy_without_a_floor():
    """It runs as an administrator, whose own floor says nothing about others."""
    effective_config_service = AsyncMock()
    effective_config_service.resolve_personal_default.side_effect = RuntimeError("stop")
    service = _assistant_service(effective_config_service)

    try:
        await service.assert_personal_default_governance_context_fit()
    except RuntimeError:
        pass

    effective_config_service.resolve_personal_default.assert_awaited_once_with()
