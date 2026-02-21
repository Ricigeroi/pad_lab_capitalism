from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.session import init_db
import models  # noqa: F401 – register all models with SQLAlchemy
from routers import enterprises, projects


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create all DB tables on startup."""
    await init_db()
    yield


app = FastAPI(
    title="Enterprise & Project Management Service",
    description="Capitalism Simulation Table – Enterprise & Project Management Microservice",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(enterprises.router)
app.include_router(projects.router)


# ── Status endpoint ───────────────────────────────────────────────────────────
@app.get("/status", tags=["Health"])
async def status():
    """Health-check endpoint."""
    return {"status": "ok", "service": "enterprise_management_service"}
