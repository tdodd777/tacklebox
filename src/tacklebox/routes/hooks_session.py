import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..utils import fail_open
from ..models import Session
from ..schemas import (
    NotificationInput,
    PreCompactInput,
    PermissionRequestInput,
    SessionEndInput,
    SessionStartInput,
    SessionStartResponse,
    SessionStartSpecific,
    UserPromptSubmitInput,
)
from ..services.audit import log_notification, log_tool_event, resolve_session
from ..services.context import build_session_summary, snapshot_pre_compact
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
