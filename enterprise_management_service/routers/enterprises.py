from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import os, socket

from core.dependencies import get_db, get_current_user_id
from core.user_client import fetch_user, fetch_users
from models.enterprise import Enterprise, EnterpriseStatus
from models.role import EnterpriseRole, RoleType
from schemas.enterprise import (
    EnterpriseCreate,
    EnterpriseUpdate,
    EnterpriseResponse,
    EnterpriseSummary,
    RoleAssign,
    RoleResponse,
    RoleWithUserResponse,
    UserInfo,
)

router = APIRouter(tags=["Enterprises"])

_REPLICA_ID = os.getenv("REPLICA_ID", "unknown")
_HOSTNAME   = socket.gethostname()


# ── GET /enterprise/whoami  (MUST be before /{enterprise_id}) ─────────────────
@router.get("/enterprise/whoami", tags=["Health"])
async def whoami():
    """Returns the identity of this specific replica – use it to verify round-robin."""
    return {
        "service":    "enterprise_management_service",
        "replica_id": _REPLICA_ID,
        "hostname":   _HOSTNAME,
    }



@router.post(
    "/enterprise/create",
    response_model=EnterpriseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_enterprise(
    payload: EnterpriseCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Create a new productive venture. Caller becomes the owner."""
    existing = await db.execute(select(Enterprise).where(Enterprise.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Enterprise name already taken")

    enterprise = Enterprise(
        name=payload.name,
        description=payload.description,
        enterprise_type=payload.enterprise_type,
        capital_invested=payload.capital_invested,
        owner_id=user_id,
    )
    db.add(enterprise)
    await db.flush()

    # Owner automatically gets STRATEGIST role
    owner_role = EnterpriseRole(
        enterprise_id=enterprise.id, user_id=user_id, role=RoleType.STRATEGIST
    )
    db.add(owner_role)
    await db.commit()

    result = await db.execute(
        select(Enterprise)
        .options(selectinload(Enterprise.members))
        .where(Enterprise.id == enterprise.id)
    )
    return result.scalar_one()


# ── GET /enterprise/{id} ──────────────────────────────────────────────────────

@router.get("/enterprise/{enterprise_id}", response_model=EnterpriseResponse)
async def get_enterprise(enterprise_id: int, db: AsyncSession = Depends(get_db)):
    """Get full details of an enterprise including its members."""
    result = await db.execute(
        select(Enterprise)
        .options(selectinload(Enterprise.members))
        .where(Enterprise.id == enterprise_id)
    )
    enterprise = result.scalar_one_or_none()
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return enterprise


# ── GET /enterprises ──────────────────────────────────────────────────────────

@router.get("/enterprises", response_model=list[EnterpriseSummary])
async def list_enterprises(
    status_filter: EnterpriseStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all enterprises, optionally filtered by status (active/stalled/abandoned)."""
    query = select(Enterprise).order_by(Enterprise.created_at.desc())
    if status_filter:
        query = query.where(Enterprise.status == status_filter)
    result = await db.execute(query)
    return result.scalars().all()


# ── PUT /enterprise/{id} ──────────────────────────────────────────────────────

@router.put("/enterprise/{enterprise_id}", response_model=EnterpriseResponse)
async def update_enterprise(
    enterprise_id: int,
    payload: EnterpriseUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Update enterprise details or status. Only the owner can modify."""
    result = await db.execute(
        select(Enterprise)
        .options(selectinload(Enterprise.members))
        .where(Enterprise.id == enterprise_id)
    )
    enterprise = result.scalar_one_or_none()
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if enterprise.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can update this enterprise")

    if payload.name is not None:
        # Check name uniqueness
        dup = await db.execute(
            select(Enterprise).where(
                Enterprise.name == payload.name, Enterprise.id != enterprise_id
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Enterprise name already taken")
        enterprise.name = payload.name
    if payload.description is not None:
        enterprise.description = payload.description
    if payload.status is not None:
        enterprise.status = payload.status
    if payload.capital_invested is not None:
        enterprise.capital_invested = payload.capital_invested

    await db.commit()
    await db.refresh(enterprise)
    return enterprise


@router.post(
    "/enterprise/{enterprise_id}/roles",
    response_model=RoleWithUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_role(
    enterprise_id: int,
    payload: RoleAssign,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Assign a role (inventor/strategist/industrialist/operator) to a user. Owner only."""
    result = await db.execute(select(Enterprise).where(Enterprise.id == enterprise_id))
    enterprise = result.scalar_one_or_none()
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if enterprise.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can assign roles")

    # Check if user already has a role in this enterprise
    existing = await db.execute(
        select(EnterpriseRole).where(
            EnterpriseRole.enterprise_id == enterprise_id,
            EnterpriseRole.user_id == payload.user_id,
        )
    )
    role_record = existing.scalar_one_or_none()
    if role_record:
        role_record.role = payload.role
    else:
        role_record = EnterpriseRole(
            enterprise_id=enterprise_id, user_id=payload.user_id, role=payload.role
        )
        db.add(role_record)

    await db.commit()
    await db.refresh(role_record)

    # Enrich with user data from user_management_service
    user_data = await fetch_user(role_record.user_id)
    user_info = UserInfo(**user_data) if user_data else None

    return RoleWithUserResponse(
        id=role_record.id,
        user_id=role_record.user_id,
        role=role_record.role,
        assigned_at=role_record.assigned_at,
        user=user_info,
    )


# ── GET /enterprise/{id}/roles ────────────────────────────────────────────────

@router.get("/enterprise/{enterprise_id}/roles", response_model=list[RoleWithUserResponse])
async def list_roles(enterprise_id: int, db: AsyncSession = Depends(get_db)):
    """List all roles in an enterprise, enriched with user profile data from user_management_service."""
    result = await db.execute(
        select(EnterpriseRole).where(EnterpriseRole.enterprise_id == enterprise_id)
    )
    roles = result.scalars().all()

    if not roles:
        return []

    # Fetch all user profiles in one concurrent batch
    user_ids = list({r.user_id for r in roles})
    users_map = await fetch_users(user_ids)

    return [
        RoleWithUserResponse(
            id=r.id,
            user_id=r.user_id,
            role=r.role,
            assigned_at=r.assigned_at,
            user=UserInfo(**users_map[r.user_id]) if r.user_id in users_map else None,
        )
        for r in roles
    ]
