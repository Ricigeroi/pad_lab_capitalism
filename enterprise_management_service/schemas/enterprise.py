from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from models.enterprise import EnterpriseType, EnterpriseStatus
from models.role import RoleType


# ── Role schemas ──────────────────────────────────────────────────────────────

class RoleAssign(BaseModel):
    user_id: int
    role: RoleType


class RoleResponse(BaseModel):
    id: int
    user_id: int
    role: RoleType
    assigned_at: datetime

    model_config = {"from_attributes": True}


class UserInfo(BaseModel):
    """Subset of user profile fetched from user_management_service."""
    username: str
    email: str
    xp: int
    capital: int


class RoleWithUserResponse(BaseModel):
    """Role assignment enriched with live user data from user_management_service."""
    id: int
    user_id: int
    role: RoleType
    assigned_at: datetime
    user: Optional[UserInfo] = None  # None when user service is unreachable

    model_config = {"from_attributes": True}


# ── Enterprise schemas ────────────────────────────────────────────────────────

class EnterpriseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=2048)
    enterprise_type: EnterpriseType
    capital_invested: int = Field(default=0, ge=0)


class EnterpriseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2048)
    status: Optional[EnterpriseStatus] = None
    capital_invested: Optional[int] = Field(default=None, ge=0)


class EnterpriseResponse(BaseModel):
    id: int
    name: str
    description: str
    enterprise_type: EnterpriseType
    status: EnterpriseStatus
    owner_id: int
    capital_invested: int
    created_at: datetime
    updated_at: datetime
    members: list[RoleResponse] = []

    model_config = {"from_attributes": True}


class EnterpriseSummary(BaseModel):
    """Lightweight response used in list endpoints."""
    id: int
    name: str
    enterprise_type: EnterpriseType
    status: EnterpriseStatus
    owner_id: int
    capital_invested: int
    created_at: datetime

    model_config = {"from_attributes": True}
