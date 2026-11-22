from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.main.models import InDB, ModelId
from eneo.users.user import UserInDBBase, UserSparse


class UserGroupState(str, Enum):
    DELETED = "deleted"


class UserGroupBase(BaseModel):
    name: str


class UserGroupCreateRequest(UserGroupBase):
    pass


class UserGroupCreate(UserGroupBase):
    tenant_id: UUID


class UserGroupUpdateRequest(BaseModel):
    name: Optional[str] = None

    users: list[ModelId] = []


class UserGroupUpdate(UserGroupUpdateRequest):
    id: UUID


class UserGroupSecurityClassificationRequest(BaseModel):
    security_classification: Optional[ModelId] = Field(
        ...,
        description="The classification the group's users work at, or null to clear it",
    )


class UserGroupInDBBase(UserGroupBase, InDB):
    tenant_id: UUID
    security_classification_id: Optional[UUID] = None


class UserGroupInDB(UserGroupInDBBase):
    users: list[UserInDBBase] = []


class UserGroupPublic(UserGroupBase, InDB):
    users: list[UserSparse] = []


class UserGroupAdminPublic(UserGroupPublic):
    """A group as an administrator reads it; the list is open to every member."""

    security_classification_id: Optional[UUID] = None
