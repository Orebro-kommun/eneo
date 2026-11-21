# Copyright (c) 2026 Sundsvalls Kommun


from dataclasses import replace
from typing import TYPE_CHECKING

from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    resolve,
    resolve_personal_default,
)
from eneo.mcp_servers.application.capability_resolver import (
    describe_capability_availability,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    allowed_capability_purposes,
    is_capability_purpose,
)
from eneo.security_classifications.domain.effective_level import meets_security_floor
from eneo.skills.domain.skill import PersonalChatPinOverride, SkillRuntimeResolution

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.governance_policy.domain.governance_policy_repo import (
        GovernancePolicyRepo,
    )
    from eneo.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.prompt_library.domain.prompt_library_repo import PromptLibraryRepo
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.skills.application.skill_service import SkillService
    from eneo.users.user import UserInDB


class EffectiveConfigService:
    """Composes the inputs to the pure resolver from live repos/services.

    Lives in `application/` because it does I/O. The resolver itself stays
    pure (no awaits, no DB) — this service is the translator between live
    state and the resolver's contract.
    """

    def __init__(
        self,
        user: "UserInDB",
        policy_repo: "GovernancePolicyRepo",
        prompt_library_repo: "PromptLibraryRepo",
        completion_model_crud_service: "CompletionModelCRUDService",
        mcp_server_settings_service: "MCPServerSettingsService",
        skill_service: "SkillService",
    ) -> None:
        self.user = user
        self.policy_repo = policy_repo
        self.prompt_library_repo = prompt_library_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.mcp_server_settings_service = mcp_server_settings_service
        self.skill_service = skill_service

    async def resolve_for(
        self,
        assistant: "Assistant",
        *,
        space_is_personal: bool,
        floor: "SecurityClassification | None" = None,
    ) -> EffectiveConfig:
        """Compute the effective config for an assistant.

        Returns the empty config for non-default assistants, non-personal
        spaces, and when no policy exists — all via the resolver's own
        short-circuits. ``floor`` is the personal space's classification.
        """
        if not assistant.is_default or not space_is_personal:
            return resolve(
                assistant=assistant,
                space_is_personal=space_is_personal,
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        return await self.resolve_personal_default(floor=floor)

    async def resolve_personal_default(
        self,
        *,
        personal_chat_pin_override: PersonalChatPinOverride | None = None,
        floor: "SecurityClassification | None" = None,
    ) -> EffectiveConfig:
        """Resolve the current personal-default policy without an Assistant.

        With a ``floor``, models and MCP servers below it never reach the
        resolver, so no default or locked model can point at one. Without it
        the policy is resolved for the whole organisation.
        """

        # A personal default assistant maps to exactly one scope today. When
        # finer scopes are added, derive the scope in this service.
        policy = await self.policy_repo.get_by_tenant(
            self.user.tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
        )
        if policy is None:
            return resolve_personal_default(
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        # Fetch only the catalogs the resolver will actually consult: it reads
        # tenant_completion_models only when models_restriction_enabled and
        # tenant_mcp_servers only when mcp_restriction_enabled. An all-disabled
        # policy row exists for any tenant whose admin merely opened the config
        # page, so skipping these keeps the chat hot path off two full-table
        # scans per resolution. These loads stay sequential because the
        # request-scoped repositories share one SQLAlchemy AsyncSession.
        async def _load_models() -> "list[CompletionModel]":
            if not policy.models_restriction_enabled:
                return []
            # Tenant-accessible completion models. Global models (tenant_id=NULL)
            # show up here because `can_access` already accounts for them.
            models = await self.completion_model_crud_service.get_available_completion_models()
            return [
                model
                for model in models
                if floor is None
                or meets_security_floor(floor, model.security_classification)
            ]

        async def _load_mcp_servers() -> "list[MCPServer]":
            if not policy.mcp_restriction_enabled:
                return []
            servers = await self.mcp_server_settings_service.get_available_mcp_servers()
            # Capability servers stay even when deactivated: the policy holds a
            # capability marker that the ask path resolves to the active
            # provider, so dropping it would silently remove the capability
            # after a provider switch. General servers must be enabled and
            # meet the floor; the ask path checks the provider it resolves.
            return [
                server
                for server in servers
                if is_capability_purpose(server.purpose)
                or (
                    server.is_enabled
                    and (
                        floor is None
                        or meets_security_floor(
                            floor, server.effective_security_classification
                        )
                    )
                )
            ]

        async def _load_prompt_text() -> str | None:
            if policy.default_prompt_library_id is None:
                return None
            entry = await self.prompt_library_repo.get(
                id=policy.default_prompt_library_id,
                tenant_id=self.user.tenant_id,
            )
            return entry.text if entry is not None else None

        async def _load_governance_skills() -> SkillRuntimeResolution:
            if policy.id is None:
                return SkillRuntimeResolution(eligible=(), blocked=())
            if personal_chat_pin_override is None:
                return await self.skill_service.resolve_governance_bindings_for_runtime(
                    policy_id=policy.id
                )
            return await self.skill_service.resolve_governance_bindings_for_runtime(
                policy_id=policy.id,
                personal_chat_pin_override=personal_chat_pin_override,
            )

        tenant_models = await _load_models()
        tenant_mcp_servers = await _load_mcp_servers()
        library_prompt_text = await _load_prompt_text()
        governance_skill_resolution = await _load_governance_skills()

        effective = resolve_personal_default(
            policy=policy,
            tenant_completion_models=tenant_models,
            tenant_mcp_servers=tenant_mcp_servers,
            library_prompt_text=library_prompt_text,
            governance_skill_resolution=governance_skill_resolution,
        )
        availability = [
            describe_capability_availability(
                tenant_mcp_servers,
                purpose,
                floor,
                user_group_ids=self.user.user_groups_ids,
                allowed_purposes=allowed_capability_purposes(self.user.permissions),
            )
            for purpose in effective.enabled_capabilities
        ]
        return replace(effective, available_capabilities=availability)
