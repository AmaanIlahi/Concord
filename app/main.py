import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal
from app.routers import admin, datasets, eval, match
from app.services.ttl_cleanup import run_ttl_cleanup

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 60 * 60  # run the TTL sweep hourly


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            run_ttl_cleanup(db)
        except Exception:
            logger.exception("Periodic TTL cleanup failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()


app = FastAPI(title="Concord", lifespan=lifespan)

app.include_router(admin.router)
app.include_router(datasets.router)
app.include_router(match.router)
app.include_router(eval.router)

# Mounted last: a root mount only serves paths not already matched by a router
# above it, so this doesn't shadow the API routes.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
