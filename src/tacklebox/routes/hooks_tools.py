import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..utils import fail_open
from ..schemas import (
    PostToolUseFailureInput,
    PostToolUseInput,
    PreToolUseInput,
    PreToolUseResponse,
    PreToolUseSpecific,
)
from ..services.audit import log_tool_event, resolve_session
from ..services.context import upsert_project_context, upsert_session_context
from ..services.coordination import check_file_lock
from ..services.responses import serialize_response

logger = logging.getLogger("tacklebox")

router = APIRouter()


@router.post("/hooks/pre-tool-use")
@fail_open
async def pre_tool_use(event: PreToolUseInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    te = await log_tool_event(
        db,
        internal_id,
        hook_event="PreToolUse",
        tool_name=event.tool_name,
        tool_input=event.tool_input,
        tool_use_id=event.tool_use_id,
    )

    # File lock check for Write/Edit
    if event.tool_name in ("Write", "Edit"):
        file_path = event.tool_input.get("file_path")
        if file_path:
            warning = await check_file_lock(db, file_path, event.session_id, event.cwd)
            if warning:
                te.decision = "warn"
                await db.commit()
                return serialize_response(
                    PreToolUseResponse(
                        hookSpecificOutput=PreToolUseSpecific(
                            permissionDecision="allow",
                            additionalContext=warning,
                        )
                    )
                )

    await db.commit()
    return {}


@router.post("/hooks/post-tool-use")
@fail_open
async def post_tool_use(event: PostToolUseInput, db: AsyncSession = Depends(get_db)):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="PostToolUse",
        tool_name=event.tool_name,
        tool_input=event.tool_input,
        tool_response=event.tool_response,
        tool_use_id=event.tool_use_id,
    )

    # Update context for Write/Edit
    if event.tool_name in ("Write", "Edit"):
        file_path = event.tool_input.get("file_path")
        if file_path:
            # Get existing list or start fresh
            from sqlalchemy import select
            from ..models import SessionContext

            existing = await db.execute(
                select(SessionContext.value)
                .where(SessionContext.cwd == event.cwd)
                .where(SessionContext.scope == "project")
                .where(SessionContext.key == "last_edited_files")
            )
            current = existing.scalar_one_or_none()
            file_list = current if isinstance(current, list) else []
            if file_path not in file_list:
                file_list.append(file_path)
            file_list = file_list[-20:]  # Keep last 20
            await upsert_project_context(
                db, internal_id, event.cwd, "last_edited_files", file_list
            )

    # Store last Bash result
    if event.tool_name == "Bash":
        await upsert_session_context(
            db,
            internal_id,
            event.cwd,
            "last_bash_result",
            {
                "command": event.tool_input.get("command"),
                "exit_code": event.tool_response.get("exitCode"),
            },
        )

    await db.commit()
    return {}


@router.post("/hooks/post-tool-use-failure")
@fail_open
async def post_tool_use_failure(
    event: PostToolUseFailureInput, db: AsyncSession = Depends(get_db)
):
    internal_id = await resolve_session(db, event.session_id, event.cwd)
    await log_tool_event(
        db,
        internal_id,
        hook_event="PostToolUseFailure",
        tool_name=event.tool_name,
        tool_input=event.tool_input,
        tool_use_id=event.tool_use_id,
        error=event.error,
    )
    await db.commit()
    return {}
