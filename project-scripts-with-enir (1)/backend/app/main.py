from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config   import settings
from app.core.database import engine

from app.api.routes.auth          import router as auth_router
from app.api.routes.dashboard     import router as dashboard_router
from app.api.routes.projects      import router as projects_router
from app.api.routes.gantt         import router as gantt_router
from app.api.routes.estimates     import router as estimates_router, jobs_router
from app.api.routes.comments      import router as comments_router
from app.api.routes.reports       import router as reports_router
from app.api.routes.materials     import router as materials_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.enir          import router as enir_router
from app.api.routes.enir_mapping  import router as enir_mapping_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title       = "Construction Management API",
    version     = "1.0.0",
    description = "Система управления строительными проектами",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.CORS_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(projects_router)
app.include_router(gantt_router)
app.include_router(estimates_router)
app.include_router(jobs_router)
app.include_router(comments_router)
app.include_router(reports_router)
app.include_router(materials_router)
app.include_router(notifications_router)
app.include_router(enir_router)
app.include_router(enir_mapping_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
