# models/__init__.py  – import all models so SQLAlchemy registers them
from models.user import User
from models.achievement import Achievement, UserAchievement
from models.equipment import Equipment, UserEquipment
from models.team import Team, TeamMember

__all__ = [
    "User",
    "Achievement",
    "UserAchievement",
    "Equipment",
    "UserEquipment",
    "Team",
    "TeamMember",
]
