from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config   import settings
from app.core.database import engine
from app.core.redis import close_redis, init_redis
from app.api.deps import get_current_user

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
from app.api.routes.fer           import router as fer_router
from app.api.routes.users         import router as users_router
from app.api.routes.admin         import router as admin_router
from app.api.routes.foreman_reports import router as foreman_reports_router
from app.api.routes.ktp           import router as ktp_router
from app.api.routes.ktp_estimate  import router as ktp_estimate_router
from app.api.routes.nw            import router as nw_router
from app.api.routes.work_plan     import router as work_plan_router
from app.api.routes.work_taxonomy import router as work_taxonomy_router
from app.api.routes.work_rates    import create_work_rate_router
from app.api.routes.activity      import router as activity_router
from app.api.routes.estimate_previews import router as estimate_previews_router
from app.api.routes.estimate_batches import router as estimate_batches_router
from app.api.routes.estimate_import_operations import router as estimate_import_operations_router
from app.services.dynamic_floor_feature_flag import validate_dynamic_floor_settings
from app.services.taxonomy_snapshot_service import resolve_config_path
from app.services.work_taxonomy_service import assert_project_hierarchy_compatible


_APP_DIR = Path(__file__).resolve().parent
work_rates_router = create_work_rate_router(
    catalog_path=resolve_config_path(settings.WORK_RATE_CATALOG_PATH),
    taxonomy_path=resolve_config_path(settings.LEGACY_WORK_TAXONOMY_PATH),
    authenticated_user_dependency=get_current_user,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_dynamic_floor_settings()
    assert_project_hierarchy_compatible()
    await init_redis()
    yield
    await close_redis()
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
app.include_router(fer_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(foreman_reports_router)
app.include_router(ktp_router)
app.include_router(ktp_estimate_router)
app.include_router(nw_router)
app.include_router(work_plan_router)
app.include_router(work_taxonomy_router)
app.include_router(work_rates_router)
app.include_router(estimate_previews_router)
app.include_router(estimate_batches_router)
app.include_router(estimate_import_operations_router)
app.include_router(activity_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
