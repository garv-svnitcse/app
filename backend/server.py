from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import os
import logging
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from db import get_db, utc_now, close_db
from seed import seed_all
from seed_part2 import seed_part2
from routers.auth_router import router as auth_router
from routers.users_router import router as users_router
from routers.notifications_router import router as notifications_router
from routers.activity_router import router as activity_router
from routers.dashboard_router import router as dashboard_router
from routers.settings_router import router as settings_router
from routers.marketplace_router import router as marketplace_router
from routers.tasks_router import router as tasks_router
from routers.employees_router import router as employees_router
from routers.opportunities_router import router as opportunities_router
from routers.connect_router import router as connect_router


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("wavygo")

app = FastAPI(title="WavyGo OS API", version="1.0.0")

api = APIRouter(prefix="/api")


@app.get("/")
@app.head("/")
async def root_head():
    return {"service": "WavyGo OS API", "status": "ok"}


@api.get("/")
async def root():
    return {"service": "WavyGo OS API", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "ok"}


api.include_router(auth_router)
api.include_router(users_router)
api.include_router(notifications_router)
api.include_router(activity_router)
api.include_router(dashboard_router)
api.include_router(settings_router)
api.include_router(marketplace_router)
api.include_router(tasks_router)
api.include_router(employees_router)
api.include_router(opportunities_router)
api.include_router(connect_router)

app.include_router(api)

cors_origins_env = os.environ.get("CORS_ORIGINS", "*").strip()
if cors_origins_env == "*" or not cors_origins_env:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"^https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def _startup():
    get_db()
    try:
        await seed_all()
        await seed_part2()
        logger.info("Seed complete (Part 1 + Part 2)")
    except Exception as e:
        logger.exception("Seed failed: %s", e)


@app.on_event("shutdown")
async def _shutdown():
    close_db()
