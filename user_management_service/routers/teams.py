from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.dependencies import get_db, get_current_user
from models.team import Team, TeamMember, TeamRole
from models.user import User
from schemas.team import TeamCreate, TeamResponse, TeamMemberResponse

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new team. The creator becomes the team leader."""
    existing = await db.execute(select(Team).where(Team.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Team name already taken")

    team = Team(name=payload.name, description=payload.description)
    db.add(team)
    await db.flush()  # get team.id before commit

    leader = TeamMember(team_id=team.id, user_id=current_user.id, role=TeamRole.LEADER)
    db.add(leader)
    await db.commit()

    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team.id)
    )
    team = result.scalar_one()
    return _build_team_response(team)


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: int, db: AsyncSession = Depends(get_db)):
    """Get team details including member list."""
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return _build_team_response(team)


@router.post("/{team_id}/join", response_model=TeamResponse)
async def join_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Join an existing team as a member."""
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    already_member = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == current_user.id,
        )
    )
    if already_member.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already a member of this team")

    member = TeamMember(team_id=team_id, user_id=current_user.id, role=TeamRole.MEMBER)
    db.add(member)
    await db.commit()

    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team_id)
    )
    team = result.scalar_one()
    return _build_team_response(team)


def _build_team_response(team: Team) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        created_at=team.created_at,
        members=[
            TeamMemberResponse(
                user_id=m.user_id,
                username=m.user.username,
                role=m.role,
                joined_at=m.joined_at,
            )
            for m in team.members
        ],
    )
