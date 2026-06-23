import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core import db
from .database import ensure_indexes
from .modules import analytics_map, applicant_portal, auth, land_applications, surveyor_registrar

app = FastAPI(
    title="LRMIS - Land Registration Management Information System",
    description="FastAPI + PyMongo backend for land registration workflow, survey tasks, maps, and analytics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_DIST = os.path.join(STATIC_DIR, "dist")
FRONTEND_ASSETS = os.path.join(FRONTEND_DIST, "assets")

app.include_router(auth.router)
app.include_router(land_applications.router)
app.include_router(applicant_portal.router)
app.include_router(surveyor_registrar.router)
app.include_router(analytics_map.router)


@app.on_event("startup")
def startup() -> None:
    if os.getenv("CREATE_INDEXES", "true").lower() == "true":
        try:
            ensure_indexes()
        except Exception as exc:
            print(f"MongoDB indexes were not created: {exc}")


@app.get("/")
def root() -> FileResponse:
    built_index = os.path.join(FRONTEND_DIST, "index.html")
    source_index = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(built_index if os.path.exists(built_index) else source_index)


@app.get("/health")
def health() -> dict[str, Any]:
    db().command("ping")
    return {"status": "ok", "database": os.getenv("MONGO_DB", "lrmis")}


if os.path.isdir(FRONTEND_ASSETS):
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith(("api/", "auth/", "applications/", "applicants/", "staff/", "analytics/", "reports/", "docs", "openapi.json", "redoc")):
        raise HTTPException(status_code=404, detail="Not found")
    built_index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(built_index):
        return FileResponse(built_index)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
