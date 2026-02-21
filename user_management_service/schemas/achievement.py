from datetime import datetime

from pydantic import BaseModel, Field


class AchievementCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="", max_length=512)
    xp_reward: int = Field(default=0, ge=0)


class AchievementResponse(BaseModel):
    id: int
    name: str
    description: str
    xp_reward: int

    model_config = {"from_attributes": True}


class UserAchievementGrant(BaseModel):
    achievement_id: int


class UserAchievementResponse(BaseModel):
    id: int
    achievement_id: int
    achievement_name: str
    xp_reward: int
    earned_at: datetime

    model_config = {"from_attributes": True}
