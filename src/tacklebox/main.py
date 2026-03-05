import asyncio
import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
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
                      AND started_at < now() - make_interval(secs => :timeout)
                      AND NOT EXISTS (
                          SELECT 1 FROM tool_events te
                          WHERE te.session_id = sessions.id
                            AND te.created_at > now() - make_interval(secs => :timeout)
                      )
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
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies exceeding MAX_REQUEST_BODY_BYTES."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
        return await call_next(request)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header when API_KEY is configured."""

    async def dispatch(self, request: Request, call_next):
        if settings.API_KEY and request.url.path != "/health":
            key = request.headers.get("x-api-key", "")
            if key != settings.API_KEY:
                return Response(
                    content='{"detail":"Invalid or missing API key"}',
                    status_code=401,
                    media_type="application/json",
                )
        return await call_next(request)


app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(APIKeyMiddleware)


@app.get("/health")
async def health():
    from .utils import fail_open_error_count

    return {"status": "ok", "fail_open_errors": fail_open_error_count}


# Import and include routers
from .routes import sessions as sessions_router
from .routes import context as context_router
from .routes import hooks_session, hooks_tools, hooks_stop

app.include_router(sessions_router.router)
app.include_router(context_router.router)
app.include_router(hooks_session.router)
app.include_router(hooks_tools.router)
app.include_router(hooks_stop.router)
