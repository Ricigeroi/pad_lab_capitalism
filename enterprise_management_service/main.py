from contextlib import asynccontextmanager
import os
import socket

from fastapi import FastAPI

from db.session import init_db
import models  # noqa: F401 – register all models with SQLAlchemy
from routers import enterprises, projects

REPLICA_ID = os.getenv("REPLICA_ID", "unknown")
HOSTNAME   = socket.gethostname()


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


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/status", tags=["Health"])
async def status():
    """Health-check endpoint."""
    return {"status": "ok", "service": "enterprise_management_service"}


@app.get("/whoami", tags=["Health"])
async def whoami():
    """Returns the identity of this specific replica – use it to verify round-robin."""
    return {
        "service":    "enterprise_management_service",
        "replica_id": REPLICA_ID,
        "hostname":   HOSTNAME,
    }

