import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..utils import fail_open
from ..models import SessionContext, StopBlock
from ..schemas import (
    StopInput,
    StopResponse,
    SubagentStartInput,
    SubagentStartResponse,
    SubagentStartSpecific,
    SubagentStopInput,
    TaskCompletedInput,
    TeammateIdleInput,
)
from ..services.audit import (
    log_stop_block,
    log_subagent_event,
    log_tool_event,
    resolve_session,
)
from ..services.context import get_incomplete_tasks
from ..services.responses import serialize_response

logger = logging.getLogger("tacklebox")

router = APIRouter()


async def _handle_stop_logic(
    db: AsyncSession,
    internal_id,
    stop_hook_active: bool,
    cwd: str,
) -> dict:
    """Shared stop logic for Stop and SubagentStop."""
    # Safety valve: check block count
    if stop_hook_active:
        block_count = await db.scalar(
            select(func.count()).select_from(StopBlock).where(
                StopBlock.session_id == internal_id
            )
        )
        if block_count >= settings.STOP_MAX_BLOCKS:
            return {}  # allow stop

    # Check for incomplete tasks
    tasks = await get_incomplete_tasks(db, cwd)
    if tasks:
        await log_stop_block(db, internal_id, str(tasks))
        await db.commit()
        return serialize_response(
            StopResponse(
                decision="block",
                reason=f"Tasks still incomplete: {', '.join(str(t) for t in tasks)}",
            )
        )

    await db.commit()
    return {}


@router.post("/hooks/stop")
@fail_open
async def stop(event: StopInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    return await _handle_stop_logic(
        db, internal_id, event.stop_hook_active, event.cwd
    )


@router.post("/hooks/subagent-stop")
@fail_open
async def subagent_stop(event: SubagentStopInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_subagent_event(
        db,
        internal_id,
        hook_event="SubagentStop",
        agent_id=event.agent_id,
        agent_type=event.agent_type,
        agent_transcript_path=event.agent_transcript_path,
        last_assistant_message=event.last_assistant_message,
    )
    return await _handle_stop_logic(
        db, internal_id, event.stop_hook_active, event.cwd
    )


@router.post("/hooks/subagent-start")
@fail_open
async def subagent_start(
    event: SubagentStartInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_subagent_event(
        db,
        internal_id,
        hook_event="SubagentStart",
        agent_id=event.agent_id,
        agent_type=event.agent_type,
    )

    # Inject project context if available
    ctx_rows = await db.execute(
        select(SessionContext.key, SessionContext.value)
        .where(SessionContext.cwd == event.cwd)
        .where(SessionContext.scope == "project")
        .order_by(SessionContext.updated_at.desc())
        .limit(10)
    )
    parts = [f"[context] {row.key}: {row.value}" for row in ctx_rows]
    await db.commit()

    if parts:
        return serialize_response(
            SubagentStartResponse(
                hookSpecificOutput=SubagentStartSpecific(
                    additionalContext="\n".join(parts)
                )
            )
        )
    return {}


@router.post("/hooks/teammate-idle")
@fail_open
async def teammate_idle(event: TeammateIdleInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="TeammateIdle",
        tool_name="TeammateIdle",
        tool_input={
            "teammate_name": event.teammate_name,
            "team_name": event.team_name,
        },
    )
    await db.commit()
    return {}


@router.post("/hooks/task-completed")
@fail_open
async def task_completed(
    event: TaskCompletedInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="TaskCompleted",
        tool_name="TaskCompleted",
        tool_input={
            "task_id": event.task_id,
            "task_subject": event.task_subject,
            "task_description": event.task_description,
            "teammate_name": event.teammate_name,
            "team_name": event.team_name,
        },
    )
    await db.commit()
    return {}
