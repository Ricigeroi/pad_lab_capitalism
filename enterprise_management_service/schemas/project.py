from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from models.project import ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=2048)
    budget: int = Field(default=0, ge=0)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2048)
    status: Optional[ProjectStatus] = None
    budget: Optional[int] = Field(default=None, ge=0)


class ProjectResponse(BaseModel):
    id: int
    enterprise_id: int
    name: str
    description: str
    status: ProjectStatus
    budget: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
