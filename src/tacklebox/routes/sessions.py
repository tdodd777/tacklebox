from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Session, ToolEvent

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
