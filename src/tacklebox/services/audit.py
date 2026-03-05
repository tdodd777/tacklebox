import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Notification,
    Session,
    StopBlock,
    SubagentEvent,
    ToolEvent,
)


async def resolve_session(
    db: AsyncSession, cc_session_id: str, cwd: str
) -> uuid.UUID:
    """Look up or create the internal session ID.

    Uses INSERT ON CONFLICT to avoid race conditions when two concurrent
    requests try to create the same session.
    """
    result = await db.execute(
        select(Session.id).where(Session.cc_session_id == cc_session_id)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Use raw INSERT ON CONFLICT to handle concurrent inserts atomically
    result = await db.execute(
        text("""
            INSERT INTO sessions (cc_session_id, cwd, source, status)
            VALUES (:cc_session_id, :cwd, 'startup', 'active')
            ON CONFLICT (cc_session_id) DO UPDATE SET cc_session_id = EXCLUDED.cc_session_id
            RETURNING id
        """),
        {"cc_session_id": cc_session_id, "cwd": cwd},
    )
    return result.scalar_one()


async def log_tool_event(
    db: AsyncSession,
    session_id: uuid.UUID,
    hook_event: str,
    tool_name: str,
    tool_input: dict | None = None,
    tool_response: dict | None = None,
    tool_use_id: str | None = None,
    error: str | None = None,
    decision: str | None = None,
) -> ToolEvent:
    event = ToolEvent(
        session_id=session_id,
        hook_event=hook_event,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response=tool_response,
        tool_use_id=tool_use_id,
        error=error,
        decision=decision,
    )
    db.add(event)
    await db.flush()
    return event


async def log_notification(
    db: AsyncSession,
    session_id: uuid.UUID,
    notification_type: str,
    title: str | None = None,
    message: str | None = None,
) -> Notification:
    notif = Notification(
        session_id=session_id,
        notification_type=notification_type,
        title=title,
        message=message,
    )
    db.add(notif)
    await db.flush()
    return notif


async def log_subagent_event(
    db: AsyncSession,
    session_id: uuid.UUID,
    hook_event: str,
    agent_id: str,
    agent_type: str,
    agent_transcript_path: str | None = None,
    last_assistant_message: str | None = None,
) -> SubagentEvent:
    event = SubagentEvent(
        session_id=session_id,
        hook_event=hook_event,
        agent_id=agent_id,
        agent_type=agent_type,
        agent_transcript_path=agent_transcript_path,
        last_assistant_message=last_assistant_message,
    )
    db.add(event)
    await db.flush()
    return event


async def log_stop_block(
    db: AsyncSession,
    session_id: uuid.UUID,
    reason: str,
) -> StopBlock:
    block = StopBlock(session_id=session_id, reason=reason)
    db.add(block)
    await db.flush()
    return block
