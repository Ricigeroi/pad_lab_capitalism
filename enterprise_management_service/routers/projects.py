from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.dependencies import get_db, get_current_user_id
from models.enterprise import Enterprise
from models.project import Project
from schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(tags=["Projects"])


@router.post(
    "/enterprise/{enterprise_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    enterprise_id: int,
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Create a project under an enterprise. Owner only."""
    result = await db.execute(select(Enterprise).where(Enterprise.id == enterprise_id))
    enterprise = result.scalar_one_or_none()
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if enterprise.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can create projects")

    project = Project(
        enterprise_id=enterprise_id,
        name=payload.name,
        description=payload.description,
        budget=payload.budget,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get(
    "/enterprise/{enterprise_id}/projects",
    response_model=list[ProjectResponse],
)
async def list_projects(enterprise_id: int, db: AsyncSession = Depends(get_db)):
    """List all projects belonging to an enterprise."""
    result = await db.execute(
        select(Project)
        .where(Project.enterprise_id == enterprise_id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.get("/enterprise/{enterprise_id}/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    enterprise_id: int, project_id: int, db: AsyncSession = Depends(get_db)
):
    """Get a single project by ID."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.enterprise_id == enterprise_id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put(
    "/enterprise/{enterprise_id}/projects/{project_id}",
    response_model=ProjectResponse,
)
async def update_project(
    enterprise_id: int,
    project_id: int,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Update a project's details or status. Owner only."""
    ent_result = await db.execute(select(Enterprise).where(Enterprise.id == enterprise_id))
    enterprise = ent_result.scalar_one_or_none()
    if not enterprise:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if enterprise.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can update projects")

    proj_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.enterprise_id == enterprise_id)
    )
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = payload.status
    if payload.budget is not None:
        project.budget = payload.budget

    await db.commit()
    await db.refresh(project)
    return project
