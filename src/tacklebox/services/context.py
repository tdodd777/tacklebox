import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, SessionContext, ToolEvent


async def build_session_summary(
    db: AsyncSession, cwd: str, cc_session_id: str, source: str
) -> str | None:
    """Build an activity summary for context injection."""
    parts: list[str] = []

    # 1. Project-scoped context keys
    ctx_rows = await db.execute(
        select(SessionContext.key, SessionContext.value)
        .where(SessionContext.cwd == cwd)
        .where(SessionContext.scope == "project")
        .order_by(SessionContext.updated_at.desc())
        .limit(10)
    )
    for row in ctx_rows:
        parts.append(f"[context] {row.key}: {row.value}")

    # 2. For resume/compact: recent activity from this session
    if source in ("resume", "compact"):
        session = await db.execute(
            select(Session.id).where(Session.cc_session_id == cc_session_id)
        )
        sid = session.scalar_one_or_none()
        if sid:
            # Recent files edited
            files = await db.execute(
                text("""
                SELECT DISTINCT tool_input->>'file_path' as file_path
                FROM tool_events
                WHERE session_id = :sid
                  AND tool_name IN ('Write', 'Edit')
                  AND hook_event = 'PostToolUse'
                ORDER BY file_path
                LIMIT 10
            """),
                {"sid": sid},
            )
            file_list = [r.file_path for r in files if r.file_path]
            if file_list:
                parts.append(f"[files edited] {', '.join(file_list)}")

            # Last Bash command and result
            last_bash = await db.execute(
                text("""
                SELECT tool_input->>'command' as cmd,
                       tool_response->>'exitCode' as exit_code
                FROM tool_events
                WHERE session_id = :sid
                  AND tool_name = 'Bash'
                  AND hook_event = 'PostToolUse'
                ORDER BY created_at DESC
                LIMIT 1
            """),
                {"sid": sid},
            )
            bash_row = last_bash.first()
            if bash_row and bash_row.cmd:
                status = (
                    "succeeded"
                    if bash_row.exit_code == "0"
                    else f"failed (exit {bash_row.exit_code})"
                )
                parts.append(f"[last command] `{bash_row.cmd}` {status}")

            # Recent failures
            failure_count = await db.scalar(
                text("""
                SELECT count(*) FROM tool_events
                WHERE session_id = :sid
                  AND hook_event = 'PostToolUseFailure'
                  AND created_at > now() - interval '1 hour'
            """),
                {"sid": sid},
            )
            if failure_count and failure_count > 0:
                parts.append(
                    f"[failures] {failure_count} tool failures in the last hour"
                )

    # 3. Other active sessions in same cwd
    other_sessions = await db.scalar(
        text("""
        SELECT count(*) FROM sessions
        WHERE cwd = :cwd AND status = 'active' AND cc_session_id != :sid
    """),
        {"cwd": cwd, "sid": cc_session_id},
    )
    if other_sessions and other_sessions > 0:
        parts.append(
            f"[coordination] {other_sessions} other active session(s) in this project"
        )

    if not parts:
        return None

    return "\n".join(parts)


async def upsert_project_context(
    db: AsyncSession,
    session_id: uuid.UUID,
    cwd: str,
    key: str,
    value: dict | list,
) -> None:
    """Upsert a project-scoped context key."""
    existing = await db.execute(
        select(SessionContext)
        .where(SessionContext.cwd == cwd)
        .where(SessionContext.scope == "project")
        .where(SessionContext.key == key)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.value = value
        row.session_id = session_id
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            SessionContext(
                session_id=session_id,
                cwd=cwd,
                scope="project",
                key=key,
                value=value,
            )
        )
    await db.flush()


async def upsert_session_context(
    db: AsyncSession,
    session_id: uuid.UUID,
    cwd: str,
    key: str,
    value: dict | list,
) -> None:
    """Upsert a session-scoped context key."""
    existing = await db.execute(
        select(SessionContext)
        .where(SessionContext.session_id == session_id)
        .where(SessionContext.scope == "session")
        .where(SessionContext.key == key)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            SessionContext(
                session_id=session_id,
                cwd=cwd,
                scope="session",
                key=key,
                value=value,
            )
        )
    await db.flush()


async def snapshot_pre_compact(
    db: AsyncSession, session_id: uuid.UUID, cwd: str
) -> None:
    """Snapshot current session state before compaction."""
    # Last 5 file paths edited
    files = await db.execute(
        text("""
        SELECT DISTINCT tool_input->>'file_path' as file_path
        FROM tool_events
        WHERE session_id = :sid
          AND tool_name IN ('Write', 'Edit')
          AND hook_event = 'PostToolUse'
        ORDER BY file_path
        LIMIT 5
    """),
        {"sid": session_id},
    )
    file_list = [r.file_path for r in files if r.file_path]

    # Last Bash result from session context
    bash_ctx = await db.execute(
        select(SessionContext.value)
        .where(SessionContext.session_id == session_id)
        .where(SessionContext.scope == "session")
        .where(SessionContext.key == "last_bash_result")
    )
    bash_value = bash_ctx.scalar_one_or_none()

    snapshot = {
        "last_edited_files": file_list,
        "last_bash_result": bash_value,
    }

    await upsert_project_context(db, session_id, cwd, "pre_compact_snapshot", snapshot)


async def get_incomplete_tasks(
    db: AsyncSession, cwd: str
) -> list | None:
    """Get incomplete tasks from project context."""
    result = await db.execute(
        select(SessionContext.value)
        .where(SessionContext.cwd == cwd)
        .where(SessionContext.scope == "project")
        .where(SessionContext.key == "incomplete_tasks")
    )
    row = result.scalar_one_or_none()
    if row and row:
        return row
    return None
