from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.users.user import UserInDB

EffectiveSecurityLevelSource = Literal["group", "default", "none"]

_FLOORS_KEY = "security_floors"


@dataclass(frozen=True)
class EffectiveSecurityLevel:
    security_classification_id: UUID | None
    source: EffectiveSecurityLevelSource
    user_group_id: UUID | None = None


_NO_LEVEL = EffectiveSecurityLevel(security_classification_id=None, source="none")


def meets_security_floor(
    floor: SecurityClassification | None,
    classification: SecurityClassification | None,
) -> bool:
    return floor is None or not floor.is_greater_than(classification)


def effective_security_level(user: "UserInDB") -> EffectiveSecurityLevel:
    """The level a user works at and where it comes from, without a lookup."""
    if not user.tenant.security_enabled:
        return _NO_LEVEL
    default_id = user.tenant.default_user_security_classification_id
    if default_id is None:
        return _NO_LEVEL
    return EffectiveSecurityLevel(
        security_classification_id=default_id, source="default"
    )


async def security_floor_for(
    session: "AsyncSession", user: "UserInDB"
) -> SecurityClassification | None:
    """The classification of the user's effective level, read once per session."""
    level_id = effective_security_level(user).security_classification_id
    if level_id is None:
        return None
    floors: dict[UUID, SecurityClassification | None] = session.info.setdefault(
        _FLOORS_KEY, {}
    )
    if level_id not in floors:
        floors[level_id] = SecurityClassification.to_domain(
            await session.scalar(
                sa.select(SecurityClassificationDBModel)
                .where(
                    SecurityClassificationDBModel.id == level_id,
                    SecurityClassificationDBModel.tenant_id == user.tenant_id,
                )
                .options(selectinload(SecurityClassificationDBModel.tenant))
            )
        )
    return floors[level_id]
