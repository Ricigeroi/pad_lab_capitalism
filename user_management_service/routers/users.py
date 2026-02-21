from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.dependencies import get_db, get_current_user
from core.security import hash_password
from models.user import User
from models.achievement import Achievement, UserAchievement
from schemas.user import UserResponse, UserProfileUpdate
from schemas.achievement import UserAchievementGrant, UserAchievementResponse

router = APIRouter(prefix="/user", tags=["Users"])


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """Get a user's public profile by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a user's profile (authenticated user can only update their own)."""
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to update another user's profile")

    if payload.email is not None:
        # Check email uniqueness
        existing = await db.execute(
            select(User).where(User.email == payload.email, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = payload.email

    if payload.password is not None:
        current_user.hashed_password = hash_password(payload.password)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/{user_id}/achievement", response_model=UserAchievementResponse, status_code=201)
async def grant_achievement(
    user_id: int,
    payload: UserAchievementGrant,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Grant an achievement to a user and award its XP.
    Only the user themselves can claim an achievement (self-service in this simulation).
    """
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Cannot grant achievements to other users")

    # Verify achievement exists
    ach_result = await db.execute(
        select(Achievement).where(Achievement.id == payload.achievement_id)
    )
    achievement = ach_result.scalar_one_or_none()
    if not achievement:
        raise HTTPException(status_code=404, detail="Achievement not found")

    # Check if already earned
    already = await db.execute(
        select(UserAchievement).where(
            UserAchievement.user_id == user_id,
            UserAchievement.achievement_id == payload.achievement_id,
        )
    )
    if already.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Achievement already earned")

    user_ach = UserAchievement(user_id=user_id, achievement_id=payload.achievement_id)
    db.add(user_ach)

    # Award XP
    current_user.xp += achievement.xp_reward

    await db.commit()
    await db.refresh(user_ach)

    return UserAchievementResponse(
        id=user_ach.id,
        achievement_id=achievement.id,
        achievement_name=achievement.name,
        xp_reward=achievement.xp_reward,
        earned_at=user_ach.earned_at,
    )


@router.get("/{user_id}/achievements", response_model=list[UserAchievementResponse])
async def list_achievements(user_id: int, db: AsyncSession = Depends(get_db)):
    """List all achievements earned by a user."""
    result = await db.execute(
        select(UserAchievement)
        .options(selectinload(UserAchievement.achievement))
        .where(UserAchievement.user_id == user_id)
    )
    rows = result.scalars().all()
    return [
        UserAchievementResponse(
            id=row.id,
            achievement_id=row.achievement.id,
            achievement_name=row.achievement.name,
            xp_reward=row.achievement.xp_reward,
            earned_at=row.earned_at,
        )
        for row in rows
    ]
