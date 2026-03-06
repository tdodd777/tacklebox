import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Session, SessionContext, ToolEvent


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago"


def _truncate_path(path: str, components: int = 2) -> str:
    """Truncate a file path to the last N components."""
    parts = path.rstrip("/").split("/")
    if len(parts) <= components:
        return path
    return "/".join(parts[-components:])


def _truncate_command(cmd: str, max_len: int = 40) -> str:
    """Truncate a command string."""
    if len(cmd) <= max_len:
        return cmd
    return cmd[:max_len - 3] + "..."


async def build_coordination_block(
    db: AsyncSession, cwd: str, cc_session_id: str
) -> str | None:
    """Build a coordination block showing per-session activity for sibling sessions.

    Uses a LEFT JOIN LATERAL to find each session's most recent tool event.
    Sessions with tool activity show the specific tool + input; sessions with
    only prompt activity (e.g. read-heavy sessions where Read isn't in the
    hook matcher) fall back to showing their last prompt timestamp.
    """
    rows = await db.execute(
        text("""
        SELECT s.cc_session_id, s.model,
               last_te.tool_name, last_te.tool_input,
               COALESCE(last_te.created_at, last_prompt.created_at, s.started_at) as last_activity,
               EXTRACT(EPOCH FROM (now() - COALESCE(last_te.created_at, last_prompt.created_at, s.started_at))) as elapsed_sec
        FROM sessions s
        LEFT JOIN LATERAL (
            SELECT tool_name, tool_input, created_at
            FROM tool_events WHERE session_id = s.id
              AND hook_event IN ('PostToolUse', 'PreToolUse')
            ORDER BY created_at DESC LIMIT 1
        ) last_te ON true
        LEFT JOIN LATERAL (
            SELECT created_at
            FROM tool_events WHERE session_id = s.id
              AND hook_event = 'UserPromptSubmit'
            ORDER BY created_at DESC LIMIT 1
        ) last_prompt ON true
        WHERE s.cwd = :cwd AND s.status = 'active' AND s.cc_session_id != :sid
          AND COALESCE(last_te.created_at, last_prompt.created_at, s.started_at)
              > now() - make_interval(secs => :active_window)
        ORDER BY last_activity DESC NULLS LAST LIMIT 5
    """),
        {
            "cwd": cwd,
            "sid": cc_session_id,
            "active_window": settings.COORDINATION_ACTIVE_WINDOW_SEC,
        },
    )
    sessions = rows.fetchall()
    if not sessions:
        return None

    lines = [f"[coordination] {len(sessions)} other active session(s) in this project:"]
    for row in sessions:
        sid_short = row.cc_session_id[:5] if len(row.cc_session_id) > 5 else row.cc_session_id
        elapsed = _format_elapsed(row.elapsed_sec)
        tool_input = row.tool_input or {}

        if row.tool_name is None:
            # No tool events — session has prompt activity or just started
            detail = "active (just started)" if row.elapsed_sec < 30 else "active (prompting)"
        elif row.tool_name in ("Write", "Edit", "Read"):
            path = tool_input.get("file_path", "unknown")
            detail = f"{row.tool_name} {_truncate_path(path)}"
        elif row.tool_name == "Bash":
            cmd = tool_input.get("command", "")
            detail = f'Bash "{_truncate_command(cmd)}"'
        else:
            detail = row.tool_name

        lines.append(f"  [session {sid_short}] {detail} ({elapsed})")

    return "\n".join(lines)


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

    # 3. Other active sessions in same cwd (enriched with per-session activity)
    coordination = await build_coordination_block(db, cwd, cc_session_id)
    if coordination:
        parts.append(coordination)

    # 4. Recently completed tasks (from TaskCompleted events in last hour)
    task_rows = await db.execute(
        text("""
        SELECT te.tool_input->>'task_subject' as subject,
               te.tool_input->>'teammate_name' as teammate,
               EXTRACT(EPOCH FROM (now() - te.created_at)) as elapsed_sec
        FROM tool_events te
        JOIN sessions s ON te.session_id = s.id
        WHERE s.cwd = :cwd
          AND te.hook_event = 'TaskCompleted'
          AND te.created_at > now() - interval '1 hour'
        ORDER BY te.created_at DESC LIMIT 5
    """),
        {"cwd": cwd},
    )
    tasks = task_rows.fetchall()
    if tasks:
        task_lines = []
        for t in tasks:
            by = f" (by {t.teammate}, {_format_elapsed(t.elapsed_sec)})" if t.teammate else f" ({_format_elapsed(t.elapsed_sec)})"
            task_lines.append(f'  "{t.subject}"{by}')
        parts.append("[tasks] Recently completed:\n" + "\n".join(task_lines))

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
    """Upsert a project-scoped context key.

    Uses INSERT ON CONFLICT against the partial unique index
    idx_ctx_project_key (cwd, key WHERE scope='project') for atomicity.
    """
    stmt = pg_insert(SessionContext).values(
        session_id=session_id,
        cwd=cwd,
        scope="project",
        key=key,
        value=value,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cwd", "key"],
        index_where=text("scope = 'project'"),
        set_={
            "value": stmt.excluded.value,
            "session_id": stmt.excluded.session_id,
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)


async def upsert_session_context(
    db: AsyncSession,
    session_id: uuid.UUID,
    cwd: str,
    key: str,
    value: dict | list,
) -> None:
    """Upsert a session-scoped context key.

    Uses INSERT ON CONFLICT against the partial unique index
    idx_ctx_session_key (session_id, key WHERE scope='session') for atomicity.
    """
    stmt = pg_insert(SessionContext).values(
        session_id=session_id,
        cwd=cwd,
        scope="session",
        key=key,
        value=value,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["session_id", "key"],
        index_where=text("scope = 'session'"),
        set_={
            "value": stmt.excluded.value,
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)


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


async def get_project_context_value(
    db: AsyncSession, cwd: str, key: str
) -> dict | list | None:
    """Get a project-scoped context value by key."""
    result = await db.execute(
        select(SessionContext.value)
        .where(SessionContext.cwd == cwd)
        .where(SessionContext.scope == "project")
        .where(SessionContext.key == key)
    )
    return result.scalar_one_or_none()


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


async def is_context_injected(
    db: AsyncSession, session_id: uuid.UUID
) -> bool:
    """Check if context has already been injected for this session."""
    result = await db.execute(
        select(SessionContext.id)
        .where(SessionContext.session_id == session_id)
        .where(SessionContext.scope == "session")
        .where(SessionContext.key == "context_injected")
    )
    return result.scalar_one_or_none() is not None
