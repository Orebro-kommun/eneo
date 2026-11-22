# Copyright (c) 2025 Sundsvalls Kommun

from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from typing_extensions import override

from eneo.base.base_repository import BaseRepository
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.main.exceptions import NotFoundException
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.database.tables.ai_models_table import (
        CompletionModels,
        EmbeddingModels,
        TranscriptionModels,
    )
    from eneo.database.tables.app_table import Apps
    from eneo.database.tables.assistant_table import Assistants
    from eneo.database.tables.collections_table import CollectionsTable
    from eneo.database.tables.integration_table import IntegrationKnowledge
    from eneo.database.tables.service_table import Services
    from eneo.database.tables.websites_table import Websites

    _Model = type[CompletionModels] | type[EmbeddingModels] | type[TranscriptionModels]
    _ModelId = InstrumentedAttribute[UUID] | InstrumentedAttribute[UUID | None]
    _Resource = (
        type[Assistants]
        | type[Apps]
        | type[Services]
        | type[CollectionsTable]
        | type[Websites]
        | type[IntegrationKnowledge]
    )


class SecurityClassificationRepoImpl(BaseRepository):
    """Implementation of the security classification repository interface."""

    def __init__(self, session: "AsyncSession", user: UserInDB) -> None:
        super().__init__()
        self.session = session
        self.user = user

    @override
    async def all(self) -> list[SecurityClassification]:  # type: ignore[override]  # covariant narrowing: list[SecurityClassification] ⊄ list[Entity] (invariant list)
        query = (
            select(SecurityClassificationDBModel)
            .where(SecurityClassificationDBModel.tenant_id == self.user.tenant_id)
            .order_by(SecurityClassificationDBModel.security_level)
            .options(selectinload(SecurityClassificationDBModel.tenant))
        )
        result = await self.session.scalars(query)
        records = result.all()

        return [
            sc
            for record in records
            if (
                sc := SecurityClassification.to_domain(
                    db_security_classification=record
                )
            )
            is not None
        ]

    @override
    async def one(self, id: UUID) -> SecurityClassification:
        security_classification = await self.one_or_none(id)
        if not security_classification:
            raise NotFoundException(f"Security classification with ID {id} not found")
        return security_classification

    @override
    async def one_or_none(self, id: UUID) -> Optional[SecurityClassification]:
        query = (
            select(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .options(selectinload(SecurityClassificationDBModel.tenant))
        )
        result = await self.session.scalar(query)

        if not result:
            return None

        return SecurityClassification.to_domain(db_security_classification=result)

    @override
    async def add(  # type: ignore[override]  # narrower param name (security_classification vs entity); both accept SecurityClassification
        self, security_classification: SecurityClassification
    ) -> SecurityClassification:
        values = {
            "name": security_classification.name,
            "description": security_classification.description,
            "security_level": security_classification.security_level,
            "tenant_id": self.user.tenant_id,
        }

        query = (
            sa.insert(SecurityClassificationDBModel)
            .values(**values)
            .returning(SecurityClassificationDBModel)
        )
        result = await self.session.execute(query)
        record = result.scalar_one()

        # After insertion, query for the record with tenant loaded
        return await self.one(record.id)

    @override
    async def update(  # type: ignore[override]  # narrower param name (security_classification vs entity); both accept SecurityClassification
        self, security_classification: SecurityClassification
    ) -> SecurityClassification:
        assert security_classification.id is not None, (
            "Security classification must have an ID to update"
        )

        # Convert domain entity to db values
        values = {
            "name": security_classification.name,
            "description": security_classification.description,
            "security_level": security_classification.security_level,
        }

        # Update the database with tenant check in the WHERE clause
        query = (
            sa.update(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == security_classification.id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .values(**values)
            .returning(SecurityClassificationDBModel)
        )

        result = await self.session.execute(query)
        record = result.scalar_one_or_none()

        # If no record was found/updated (wrong ID or wrong tenant), raise exception
        if record is None:
            raise NotFoundException(
                f"Security classification with ID {security_classification.id} not found"
            )

        # Query for the record with tenant loaded
        return await self.one(record.id)

    async def count_usages(self, id: UUID) -> dict[str, int]:
        """Count how many rows currently reference this classification.

        Used by the service before deletion: a classification's FK is
        `ON DELETE SET NULL`, so dropping a row in active use would
        silently relabel every model / space / MCP server that referenced
        it as "no classification". For a system whose whole point is
        to gate model availability by classification, that's a privilege
        escalation by accident — the admin sees "1 row deleted" while
        actually loosening access on N other rows.
        """
        from eneo.database.tables.ai_models_table import (
            CompletionModels,
            EmbeddingModels,
            RerankModels,
            TranscriptionModels,
        )
        from eneo.database.tables.mcp_server_table import MCPServers
        from eneo.database.tables.spaces_table import Spaces
        from eneo.database.tables.tenant_table import Tenants
        from eneo.database.tables.user_groups_table import UserGroups
        from eneo.user_groups.user_group import UserGroupState

        # Soft-deleted completion and rerank models still carry their FK to
        # the classification, but they're not active anymore — counting them
        # produces an "in use" error the admin can't act on. Embedding /
        # transcription models have no soft-delete column today.
        counts = await self.session.execute(
            sa.select(
                sa.select(sa.func.count())
                .where(
                    CompletionModels.security_classification_id == id,
                    CompletionModels.deleted_at.is_(None),
                )
                .scalar_subquery()
                .label("completion_models"),
                sa.select(sa.func.count())
                .where(EmbeddingModels.security_classification_id == id)
                .scalar_subquery()
                .label("embedding_models"),
                sa.select(sa.func.count())
                .where(TranscriptionModels.security_classification_id == id)
                .scalar_subquery()
                .label("transcription_models"),
                sa.select(sa.func.count())
                .where(
                    RerankModels.security_classification_id == id,
                    RerankModels.deleted_at.is_(None),
                )
                .scalar_subquery()
                .label("rerank_models"),
                sa.select(sa.func.count())
                .where(Spaces.security_classification_id == id)
                .scalar_subquery()
                .label("spaces"),
                sa.select(sa.func.count())
                .where(MCPServers.security_classification_id == id)
                .scalar_subquery()
                .label("mcp_servers"),
                sa.select(sa.func.count())
                .where(Tenants.default_user_security_classification_id == id)
                .scalar_subquery()
                .label("default_user_level"),
                sa.select(sa.func.count())
                .where(
                    UserGroups.security_classification_id == id,
                    sa.or_(
                        UserGroups.state.is_(None),
                        UserGroups.state != UserGroupState.DELETED,
                    ),
                )
                .scalar_subquery()
                .label("user_groups"),
            )
        )
        row = counts.one()
        return {
            "completion_models": row.completion_models,
            "embedding_models": row.embedding_models,
            "transcription_models": row.transcription_models,
            "rerank_models": row.rerank_models,
            "spaces": row.spaces,
            "mcp_servers": row.mcp_servers,
            "default_user_level": row.default_user_level,
            "user_groups": row.user_groups,
        }

    async def spaces_below_default_level(
        self,
    ) -> list[sa.Row[tuple[UUID, str, UUID | None]]]:
        """Shared spaces whose classification is below the default user level."""
        from eneo.database.tables.spaces_table import Spaces
        from eneo.database.tables.tenant_table import Tenants

        classification = SecurityClassificationDBModel
        default = (
            sa.select(classification.security_level)
            .join(
                Tenants,
                Tenants.default_user_security_classification_id == classification.id,
            )
            .where(Tenants.id == self.user.tenant_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            sa.select(Spaces.id, Spaces.name, Spaces.security_classification_id)
            .outerjoin(
                classification, classification.id == Spaces.security_classification_id
            )
            .where(
                Spaces.tenant_id == self.user.tenant_id,
                # Neither a personal space nor the organisation's own.
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_not(None),
                sa.func.coalesce(
                    classification.security_level < default, default.is_not(None)
                ),
            )
            .order_by(Spaces.name)
        )
        return list(result.all())

    async def count_level_impact(
        self, level: int | None, user_group_id: UUID | None
    ) -> dict[str, int]:
        """Count what changes if `level` becomes a group's level, or the default.

        A resource counts when the new level stops it and the current one
        does not. Only personal spaces are looked at.
        """
        from eneo.database.tables.ai_models_table import (
            CompletionModels,
            EmbeddingModels,
            TranscriptionModels,
        )
        from eneo.database.tables.app_table import Apps
        from eneo.database.tables.assistant_table import Assistants
        from eneo.database.tables.collections_table import CollectionsTable
        from eneo.database.tables.integration_table import IntegrationKnowledge
        from eneo.database.tables.service_table import Services
        from eneo.database.tables.spaces_table import Spaces
        from eneo.database.tables.tenant_table import Tenants
        from eneo.database.tables.user_groups_table import UserGroups
        from eneo.database.tables.users_table import Users, usergroups_users_table
        from eneo.database.tables.websites_table import Websites
        from eneo.user_groups.user_group import UserGroupState

        tenant_id = self.user.tenant_id
        proposed = sa.literal(level, sa.Integer)
        classification = SecurityClassificationDBModel

        not_deleted = sa.or_(
            UserGroups.state.is_(None), UserGroups.state != UserGroupState.DELETED
        )
        if user_group_id is not None and not await self.session.scalar(
            sa.select(
                sa.exists().where(
                    UserGroups.id == user_group_id,
                    UserGroups.tenant_id == tenant_id,
                    not_deleted,
                )
            )
        ):
            raise NotFoundException(f"User group with ID {user_group_id} not found")

        group_level = classification.security_level
        new_group_level = (
            group_level
            if user_group_id is None
            else sa.case((UserGroups.id == user_group_id, proposed), else_=group_level)
        )
        from_groups = (
            sa.select(
                usergroups_users_table.c.user_id,
                sa.func.max(group_level).label("old"),
                sa.func.max(new_group_level).label("new"),
            )
            .join(UserGroups, UserGroups.id == usergroups_users_table.c.user_group_id)
            .outerjoin(
                classification,
                classification.id == UserGroups.security_classification_id,
            )
            .where(
                UserGroups.tenant_id == tenant_id,
                not_deleted,
            )
            .group_by(usergroups_users_table.c.user_id)
            .subquery()
        )
        default = (
            sa.select(classification.security_level)
            .join(
                Tenants,
                Tenants.default_user_security_classification_id == classification.id,
            )
            .where(Tenants.id == tenant_id)
            .scalar_subquery()
        )
        old = sa.func.coalesce(from_groups.c.old, default)
        new = sa.func.coalesce(
            from_groups.c.new, proposed if user_group_id is None else default
        )
        affected = (
            sa.select(Users.id, old.label("old"), new.label("new"))
            .outerjoin(from_groups, from_groups.c.user_id == Users.id)
            .where(
                Users.tenant_id == tenant_id,
                Users.deleted_at.is_(None),
                old.is_distinct_from(new),
            )
            .cte("affected")
        )

        def below(
            model: "_Model", column: "_ModelId", floor: sa.ColumnElement[int]
        ) -> sa.ColumnElement[bool]:
            """The resource uses a model that does not meet the floor."""
            model_level = (
                sa.select(classification.security_level)
                .where(classification.id == model.security_classification_id)
                .scalar_subquery()
            )
            return sa.and_(
                floor.is_not(None),
                sa.exists().where(
                    model.id == column,
                    sa.func.coalesce(model_level < floor, sa.true()),
                ),
            )

        def count(
            resource: "_Resource",
            *model_links: "tuple[_Model, _ModelId]",
            where: sa.ColumnElement[bool] = sa.true(),
        ):
            def stopped(floor: sa.ColumnElement[int]) -> sa.ColumnElement[bool]:
                return sa.or_(*(below(*link, floor) for link in model_links))

            return (
                sa.select(sa.func.count())
                .select_from(resource)
                .join(Spaces, Spaces.id == resource.space_id)
                .join(affected, affected.c.id == Spaces.user_id)
                .where(where, stopped(affected.c.new), sa.not_(stopped(affected.c.old)))
                .scalar_subquery()
            )

        row = (
            await self.session.execute(
                sa.select(
                    sa.select(sa.func.count())
                    .select_from(affected)
                    .scalar_subquery()
                    .label("affected_users"),
                    count(
                        Assistants,
                        (CompletionModels, Assistants.completion_model_id),
                        # The personal default assistant moves to another model.
                        where=Assistants.is_default.is_(False),
                    ).label("assistants"),
                    count(
                        Apps,
                        (CompletionModels, Apps.completion_model_id),
                        (TranscriptionModels, Apps.transcription_model_id),
                    ).label("apps"),
                    count(
                        Services, (CompletionModels, Services.completion_model_id)
                    ).label("services"),
                    count(
                        CollectionsTable,
                        (EmbeddingModels, CollectionsTable.embedding_model_id),
                    ).label("collections"),
                    count(
                        Websites, (EmbeddingModels, Websites.embedding_model_id)
                    ).label("websites"),
                    count(
                        IntegrationKnowledge,
                        (EmbeddingModels, IntegrationKnowledge.embedding_model_id),
                    ).label("integration_knowledge"),
                )
            )
        ).one()
        return {
            "affected_users": row.affected_users,
            "assistants": row.assistants,
            "apps": row.apps,
            "services": row.services,
            "knowledge_sources": row.collections
            + row.websites
            + row.integration_knowledge,
        }

    @override
    async def delete(self, id: UUID) -> None:
        query = (
            sa.delete(SecurityClassificationDBModel)
            .where(
                sa.and_(
                    SecurityClassificationDBModel.id == id,
                    SecurityClassificationDBModel.tenant_id == self.user.tenant_id,
                )
            )
            .returning(SecurityClassificationDBModel.id)
        )

        result = await self.session.execute(query)
        deleted_id = result.scalar_one_or_none()

        # If no record was deleted (wrong ID or wrong tenant), raise exception
        if deleted_id is None:
            raise NotFoundException(f"Security classification with ID {id} not found")
