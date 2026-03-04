import asyncio
import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import async_session, engine
from .utils import fail_open  # noqa: F401 — re-export for convenience

logger = logging.getLogger("tacklebox")


async def cleanup_stale_sessions():
    while True:
        await asyncio.sleep(300)
        try:
            async with async_session() as db:
                await db.execute(
                    text("""
                    UPDATE sessions SET status = 'interrupted', ended_at = now()
                    WHERE status = 'active'
                      AND id NOT IN (
                          SELECT DISTINCT session_id FROM tool_events
                          WHERE created_at > now() - make_interval(secs => :timeout)
                      )
                      AND started_at < now() - make_interval(secs => :timeout)
                """),
                    {"timeout": settings.SESSION_TIMEOUT_SEC},
                )
                await db.commit()
        except Exception:
            logger.error(f"Stale session cleanup failed:\n{traceback.format_exc()}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # Check DB connectivity
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.warning(f"Database unavailable at startup: {e}. Hooks will fail open.")

    # Start background tasks
    cleanup_task = asyncio.create_task(cleanup_stale_sessions())

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="Tacklebox", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Import and include routers
from .routes import sessions as sessions_router
from .routes import context as context_router
from .routes import hooks_session, hooks_tools, hooks_stop

app.include_router(sessions_router.router)
app.include_router(context_router.router)
app.include_router(hooks_session.router)
app.include_router(hooks_tools.router)
app.include_router(hooks_stop.router)
