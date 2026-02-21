from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.session import init_db
import models  # noqa: F401 – ensure all models are registered with SQLAlchemy
from routers import auth, users, teams, achievements


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations (create_all) on startup."""
    await init_db()
    yield


app = FastAPI(
    title="User Management Service",
    description="Capitalism Simulation Table – User Management Microservice",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(teams.router)
app.include_router(achievements.router)


# ── Status endpoint ───────────────────────────────────────────────────────────
@app.get("/status", tags=["Health"])
async def status():
    """Health-check endpoint."""
    return {"status": "ok", "service": "user_management_service"}
