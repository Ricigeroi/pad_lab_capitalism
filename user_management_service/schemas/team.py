from datetime import datetime

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=512)


class TeamMemberResponse(BaseModel):
    user_id: int
    username: str
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class TeamResponse(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    members: list[TeamMemberResponse] = []

    model_config = {"from_attributes": True}
