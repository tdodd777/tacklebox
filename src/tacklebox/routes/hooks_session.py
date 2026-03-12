import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..utils import fail_open
from ..models import Session, SessionContext
from ..schemas import (
    ConfigChangeInput,
    InstructionsLoadedInput,
    NotificationInput,
    PreCompactInput,
    PermissionRequestInput,
    SessionEndInput,
    SessionStartInput,
    SessionStartResponse,
    SessionStartSpecific,
    UserPromptSubmitInput,
    UserPromptSubmitResponse,
    UserPromptSubmitSpecific,
)
from ..services.audit import log_notification, log_tool_event, resolve_session
from ..services.context import (
    build_coordination_block,
    build_session_summary,
    extract_session_intent,
    is_context_injected,
    snapshot_pre_compact,
    upsert_session_context,
)
from ..services.responses import serialize_response

logger = logging.getLogger("tacklebox")

router = APIRouter()


@router.post("/hooks/session-start")
@fail_open
async def session_start(event: SessionStartInput, db: AsyncSession = Depends(get_db)):
    # Upsert session
    existing = await db.execute(
        select(Session).where(Session.cc_session_id == event.session_id)
    )
    session = existing.scalar_one_or_none()
    if session:
        session.source = event.source.value
        session.model = event.model
        session.permission_mode = event.permission_mode.value
        session.status = "active"
        session.started_at = datetime.now(timezone.utc)
        session.ended_at = None
        await db.flush()
    else:
        session = Session(
            cc_session_id=event.session_id,
            cwd=event.cwd,
            model=event.model,
            source=event.source.value,
            permission_mode=event.permission_mode.value,
            status="active",
        )
        db.add(session)
        await db.flush()

    # Build context summary
    summary = await build_session_summary(
        db, event.cwd, event.session_id, event.source.value
    )

    # Set context_injected flag for non-startup sources.
    # Startup sessions skip this because Claude Code discards the SessionStart
    # response for new sessions (anthropics/claude-code#10373). UserPromptSubmit
    # handles injection for startup sessions instead.
    if event.source.value != "startup":
        await upsert_session_context(
            db, session.id, event.cwd, "context_injected", {"injected": True}
        )

    await db.commit()

    if summary:
        return serialize_response(
            SessionStartResponse(
                hookSpecificOutput=SessionStartSpecific(additionalContext=summary)
            )
        )
    return {}


@router.post("/hooks/session-end")
@fail_open
async def session_end(event: SessionEndInput, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Session).where(Session.cc_session_id == event.session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        logger.warning(f"SessionEnd for unknown session: {event.session_id}")
        return {}
    session.status = "completed"
    session.ended_at = datetime.now(timezone.utc)
    session.end_reason = event.reason
    await db.commit()
    return {}


@router.post("/hooks/notification")
@fail_open
async def notification(event: NotificationInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_notification(
        db, internal_id, event.notification_type, event.title, event.message
    )
    await db.commit()
    return {}


@router.post("/hooks/pre-compact")
@fail_open
async def pre_compact(event: PreCompactInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await snapshot_pre_compact(db, internal_id, event.cwd)
    await db.commit()
    return {}


@router.post("/hooks/user-prompt")
@fail_open
async def user_prompt(
    event: UserPromptSubmitInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    # Log prompt hash/length (respect LOG_PROMPTS)
    if settings.LOG_PROMPTS:
        log_value = event.prompt
    else:
        log_value = f"[{len(event.prompt)} chars, hash={hashlib.sha256(event.prompt.encode()).hexdigest()[:12]}]"
    await log_tool_event(
        db,
        internal_id,
        hook_event="UserPromptSubmit",
        tool_name="UserPrompt",
        tool_input={"prompt_info": log_value},
    )

    # Store session intent from first prompt only
    if settings.LOG_SESSION_INTENT:
        intent_exists = await db.execute(
            select(SessionContext.id)
            .where(SessionContext.session_id == internal_id)
            .where(SessionContext.scope == "session")
            .where(SessionContext.key == "session_intent")
        )
        if intent_exists.scalar_one_or_none() is None:
            intent = extract_session_intent(event.prompt)
            await upsert_session_context(
                db, internal_id, event.cwd, "session_intent", {"intent": intent}
            )

    # Inject context on first prompt if not already done (fallback for startup
    # sessions where SessionStart response is discarded by Claude Code).
    if not await is_context_injected(db, internal_id):
        summary = await build_session_summary(
            db, event.cwd, event.session_id, "startup"
        )
        await upsert_session_context(
            db, internal_id, event.cwd, "context_injected", {"injected": True}
        )
        await db.commit()
        if summary:
            return serialize_response(
                UserPromptSubmitResponse(
                    hookSpecificOutput=UserPromptSubmitSpecific(
                        additionalContext=summary
                    )
                )
            )
        return {}

    # Already injected full context — check if coordination needs refresh
    coordination_ctx = await db.execute(
        select(SessionContext.value)
        .where(SessionContext.session_id == internal_id)
        .where(SessionContext.scope == "session")
        .where(SessionContext.key == "coordination_last_injected")
    )
    last_injected = coordination_ctx.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    stale = (
        last_injected is None
        or (now - datetime.fromisoformat(last_injected["at"])).total_seconds()
        > settings.COORDINATION_REFRESH_SEC
    )

    if stale:
        block = await build_coordination_block(db, event.cwd, event.session_id)
        if block:
            await upsert_session_context(
                db, internal_id, event.cwd,
                "coordination_last_injected", {"at": now.isoformat()}
            )
            await db.commit()
            return serialize_response(
                UserPromptSubmitResponse(
                    hookSpecificOutput=UserPromptSubmitSpecific(
                        additionalContext=f"[coordination update]\n{block}"
                    )
                )
            )

    await db.commit()
    return {}


@router.post("/hooks/permission-request")
@fail_open
async def permission_request(
    event: PermissionRequestInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="PermissionRequest",
        tool_name=event.tool_name,
        tool_input=event.tool_input,
    )
    await db.commit()
    return {}


@router.post("/hooks/instructions-loaded")
@fail_open
async def instructions_loaded(
    event: InstructionsLoadedInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="InstructionsLoaded",
        tool_name="InstructionsLoaded",
        tool_input={
            "file_path": event.file_path,
            "memory_type": event.memory_type,
            "load_reason": event.load_reason,
            "globs": event.globs,
            "trigger_file_path": event.trigger_file_path,
            "parent_file_path": event.parent_file_path,
        },
    )
    await db.commit()
    return {}


@router.post("/hooks/config-change")
@fail_open
async def config_change(
    event: ConfigChangeInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="ConfigChange",
        tool_name="ConfigChange",
        tool_input={
            "source": event.source,
            "file_path": event.file_path,
        },
    )
    await db.commit()
    return {}
