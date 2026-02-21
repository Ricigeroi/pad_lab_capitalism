from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.dependencies import get_db
from models.achievement import Achievement
from schemas.achievement import AchievementCreate, AchievementResponse

router = APIRouter(prefix="/achievements", tags=["Achievements"])


@router.post("", response_model=AchievementResponse, status_code=status.HTTP_201_CREATED)
async def create_achievement(
    payload: AchievementCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new achievement definition (admin / seeding use)."""
    existing = await db.execute(select(Achievement).where(Achievement.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Achievement with this name already exists")

    achievement = Achievement(
        name=payload.name,
        description=payload.description,
        xp_reward=payload.xp_reward,
    )
    db.add(achievement)
    await db.commit()
    await db.refresh(achievement)
    return achievement


@router.get("", response_model=list[AchievementResponse])
async def list_achievements(db: AsyncSession = Depends(get_db)):
    """List all available achievements."""
    result = await db.execute(select(Achievement).order_by(Achievement.id))
    return result.scalars().all()


@router.get("/{achievement_id}", response_model=AchievementResponse)
async def get_achievement(achievement_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single achievement by ID."""
    result = await db.execute(select(Achievement).where(Achievement.id == achievement_id))
    achievement = result.scalar_one_or_none()
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")
    return achievement
