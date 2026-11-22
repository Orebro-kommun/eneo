from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence
from uuid import UUID

from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.embedding_models.application.embedding_model_crud_service import (
        EmbeddingModelCRUDService,
    )
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )
    from eneo.transcription_models.application.transcription_model_crud_service import (
        TranscriptionModelCRUDService,
    )
    from eneo.users.user import UserInDB


class _Model(Protocol):
    @property
    def can_access(self) -> bool: ...

    @property
    def security_classification(self) -> "SecurityClassification | None": ...


@dataclass(frozen=True)
class SecurityLevelImpact:
    affected_users: int
    assistants: int
    apps: int
    services: int
    knowledge_sources: int
    completion_models: int
    embedding_models: int
    transcription_models: int


def _usable(models: Sequence[_Model], level: "SecurityClassification | None") -> int:
    # Compared by level, so the answer holds while classification is disabled.
    return sum(
        model.can_access
        and (
            level is None
            or (
                model.security_classification is not None
                and model.security_classification.security_level >= level.security_level
            )
        )
        for model in models
    )


class SecurityLevelImpactService:
    """What setting a security level on a group, or as the default, would change."""

    def __init__(
        self,
        user: "UserInDB",
        repo: "SecurityClassificationRepoImpl",
        completion_model_crud_service: "CompletionModelCRUDService",
        embedding_model_crud_service: "EmbeddingModelCRUDService",
        transcription_model_crud_service: "TranscriptionModelCRUDService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.completion_model_crud_service = completion_model_crud_service
        self.embedding_model_crud_service = embedding_model_crud_service
        self.transcription_model_crud_service = transcription_model_crud_service

    async def usable_completion_models(
        self, level: "SecurityClassification | None"
    ) -> int:
        return _usable(
            await self.completion_model_crud_service.get_completion_models(), level
        )

    @validate_permissions(Permission.ADMIN)
    async def spaces_below_default_level(self):
        return await self.repo.spaces_below_default_level()

    @validate_permissions(Permission.ADMIN)
    async def preview(
        self, classification_id: UUID | None, user_group_id: UUID | None
    ) -> SecurityLevelImpact:
        """Without a group the level is previewed as the organisation's default."""
        level = (
            await self.repo.one(id=classification_id)
            if classification_id is not None
            else None
        )
        counts = await self.repo.count_level_impact(
            level.security_level if level is not None else None, user_group_id
        )
        return SecurityLevelImpact(
            **counts,
            completion_models=await self.usable_completion_models(level),
            embedding_models=_usable(
                await self.embedding_model_crud_service.get_embedding_models(), level
            ),
            transcription_models=_usable(
                await self.transcription_model_crud_service.get_transcription_models(),
                level,
            ),
        )
