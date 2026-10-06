from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import os
import asyncio
import logging
from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.middleware.cors import CORSMiddleware

from db import get_db, utc_now, close_db
from seed import seed_all
from routers.auth_router import router as auth_router, ensure_password_reset_indexes
from routers.users_router import router as users_router
from routers.notifications_router import router as notifications_router
from routers.activity_router import router as activity_router
from routers.dashboard_router import router as dashboard_router
from routers.settings_router import router as settings_router
from routers.marketplace_router import router as marketplace_router
from routers.tasks_router import router as tasks_router
from routers.employees_router import router as employees_router
from routers.resources_router import router as resources_router
from routers.opportunities_router import router as opportunities_router
from routers.connect_router import router as connect_router
from routers.vault_router import (
    router as vault_router, ensure_indexes as ensure_vault_indexes, send_expiry_reminders as send_vault_reminders,
)
from routers.finance_router import router as finance_router, ensure_indexes as ensure_finance_indexes
from routers.crm_router import router as crm_router, ensure_indexes as ensure_crm_indexes
from routers.marketing_router import router as marketing_router, ensure_indexes as ensure_marketing_indexes
from routers.analytics_router import router as analytics_router, ensure_indexes as ensure_analytics_indexes
from routers.ai_router import router as ai_router
from routers.calendar_router import (
    router as calendar_router, ensure_indexes as ensure_calendar_indexes, reminder_loop as calendar_reminder_loop,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("wavygo")

app = FastAPI(title="WavyGo OS API", version="1.0.0")

api = APIRouter(prefix="/api")


@app.exception_handler(ValueError)
async def _invalid_value(request: Request, exc: ValueError):
    # hub_utils.oid() and similar helpers raise ValueError for malformed input; that is a client error.
    # pydantic's ValidationError is also a ValueError, but raised inside server code it is our bug.
    if isinstance(exc, PydanticValidationError):
        logger.exception("Unhandled validation error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    return JSONResponse(status_code=400, content={"detail": str(exc) or "Invalid value"})


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
api.include_router(resources_router)
api.include_router(opportunities_router)
api.include_router(connect_router)
api.include_router(calendar_router)
api.include_router(vault_router)
api.include_router(finance_router)
api.include_router(crm_router)
api.include_router(marketing_router)
api.include_router(analytics_router)
api.include_router(ai_router)

app.include_router(api)

cors_origins_env = os.environ.get("CORS_ORIGINS", "*").strip()
if cors_origins_env == "*" or not cors_origins_env:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
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
        expose_headers=["Content-Disposition"],
    )


@app.on_event("startup")
async def _startup():
    get_db()
    try:
        await seed_all()
        logger.info("Startup seed complete (Founder account created from env only if none existed).")
    except Exception as e:
        logger.exception("Startup seed failed: %s", e)
    try:
        db = get_db()
        await ensure_calendar_indexes(db)
        await db.channel_reads.create_index([("channel_id", 1), ("user_id", 1)], unique=True)
        await db.messages.create_index([("channel_id", 1), ("created_at", 1)])
        await ensure_password_reset_indexes(db)
        await ensure_vault_indexes(db)
        await ensure_finance_indexes(db)
        await ensure_analytics_indexes(db)
        await ensure_crm_indexes(db)
        await ensure_marketing_indexes(db)
        await db.task_files.create_index("task_id")
        await db.task_files.create_index("legacy_key", unique=True, sparse=True)
    except Exception as e:
        logger.exception("Index creation failed: %s", e)
    app.state.calendar_reminders = asyncio.create_task(calendar_reminder_loop())
    app.state.hourly_jobs = asyncio.create_task(_hourly_jobs())
    app.state.presence = asyncio.create_task(_presence_loop())


async def _presence_loop():
    """Marks users offline once they have made no request for PRESENCE_TIMEOUT
    (closing the tab never logs out, so logout alone can't keep "online" honest)."""
    from datetime import datetime, timezone
    from auth_utils import PRESENCE_TIMEOUT
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - PRESENCE_TIMEOUT
            await get_db().users.update_many(
                {"online": True, "$or": [{"last_seen": {"$lt": cutoff}}, {"last_seen": {"$exists": False}}]},
                {"$set": {"online": False}},
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Presence update failed")
        await asyncio.sleep(60)


async def _hourly_jobs():
    """Low-frequency background work (document expiry reminders)."""
    while True:
        try:
            await send_vault_reminders(get_db())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hourly background job failed")
        await asyncio.sleep(3600)


@app.on_event("shutdown")
async def _shutdown():
    for name in ("calendar_reminders", "hourly_jobs", "presence"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()
    close_db()
