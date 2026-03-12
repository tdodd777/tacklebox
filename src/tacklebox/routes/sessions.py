from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Notification, Session, SessionContext, StopBlock, SubagentEvent, ToolEvent

router = APIRouter()


@router.get("/sessions")
async def list_sessions(
    status: Literal["active", "completed", "interrupted"] | None = Query(None),
    cwd: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Session).order_by(Session.started_at.desc())
    if status:
        q = q.where(Session.status == status)
    if cwd:
        q = q.where(Session.cwd == cwd)
    result = await db.execute(q.offset(offset).limit(limit))
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "cc_session_id": s.cc_session_id,
            "cwd": s.cwd,
            "model": s.model,
            "source": s.source,
            "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolEvent)
        .where(ToolEvent.session_id == session_id)
        .order_by(ToolEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "hook_event": e.hook_event,
            "tool_name": e.tool_name,
            "tool_input": e.tool_input,
            "tool_response": e.tool_response,
            "tool_use_id": e.tool_use_id,
            "error": e.error,
            "decision": e.decision,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


ALL_HOOKS = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "Stop",
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
    "SubagentStart", "SubagentStop", "Notification", "PreCompact",
    "TeammateIdle", "TaskCompleted", "InstructionsLoaded", "ConfigChange",
]


@router.get("/hooks/status")
async def hooks_status(db: AsyncSession = Depends(get_db)):
    """Diagnostic: last-seen timestamp and 24h count for each hook event type."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    hooks = {h: {"last_seen": None, "count_24h": 0} for h in ALL_HOOKS}

    # SessionStart — from sessions table
    row = (await db.execute(
        select(
            func.max(Session.started_at),
            func.count(case((Session.started_at >= since, 1)))
        )
    )).one()
    hooks["SessionStart"] = {
        "last_seen": row[0].isoformat() if row[0] else None,
        "count_24h": row[1],
    }

    # SessionEnd — from sessions where ended_at is set
    row = (await db.execute(
        select(
            func.max(Session.ended_at),
            func.count(case((Session.ended_at >= since, 1)))
        ).where(Session.ended_at.is_not(None))
    )).one()
    hooks["SessionEnd"] = {
        "last_seen": row[0].isoformat() if row[0] else None,
        "count_24h": row[1],
    }

    # Tool events — grouped by hook_event
    rows = (await db.execute(
        select(
            ToolEvent.hook_event,
            func.max(ToolEvent.created_at),
            func.count(case((ToolEvent.created_at >= since, 1)))
        ).group_by(ToolEvent.hook_event)
    )).all()
    for hook_event, last_seen, count_24h in rows:
        if hook_event in hooks:
            hooks[hook_event] = {
                "last_seen": last_seen.isoformat() if last_seen else None,
                "count_24h": count_24h,
            }

    # Subagent events — grouped by hook_event
    rows = (await db.execute(
        select(
            SubagentEvent.hook_event,
            func.max(SubagentEvent.created_at),
            func.count(case((SubagentEvent.created_at >= since, 1)))
        ).group_by(SubagentEvent.hook_event)
    )).all()
    for hook_event, last_seen, count_24h in rows:
        if hook_event in hooks:
            hooks[hook_event] = {
                "last_seen": last_seen.isoformat() if last_seen else None,
                "count_24h": count_24h,
            }

    # Notifications
    row = (await db.execute(
        select(
            func.max(Notification.created_at),
            func.count(case((Notification.created_at >= since, 1)))
        )
    )).one()
    hooks["Notification"] = {
        "last_seen": row[0].isoformat() if row[0] else None,
        "count_24h": row[1],
    }

    # Stop — from stop_blocks (only captures blocked stops)
    row = (await db.execute(
        select(
            func.max(StopBlock.created_at),
            func.count(case((StopBlock.created_at >= since, 1)))
        )
    )).one()
    hooks["Stop"] = {
        "last_seen": row[0].isoformat() if row[0] else None,
        "count_24h": row[1],
    }

    # PreCompact — from session_context snapshots
    row = (await db.execute(
        select(
            func.max(SessionContext.updated_at),
            func.count(case((SessionContext.updated_at >= since, 1)))
        ).where(SessionContext.key == "pre_compact_snapshot")
    )).one()
    hooks["PreCompact"] = {
        "last_seen": row[0].isoformat() if row[0] else None,
        "count_24h": row[1],
    }

    never_seen = [h for h in ALL_HOOKS if hooks[h]["last_seen"] is None]

    return {"hooks": hooks, "never_seen": never_seen}
