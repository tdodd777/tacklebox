from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings

FILE_LOCK_QUERY = """
SELECT
    s.cc_session_id,
    te.created_at,
    te.tool_name
FROM tool_events te
JOIN sessions s ON s.id = te.session_id
WHERE te.hook_event = 'PostToolUse'
  AND te.tool_name IN ('Write', 'Edit')
  AND te.tool_input->>'file_path' = :target_file_path
  AND s.cc_session_id != :current_session_id
  AND s.status = 'active'
  AND te.created_at > now() - make_interval(secs => :staleness_sec)
ORDER BY te.created_at DESC
LIMIT 1;
"""


async def check_file_lock(
    db: AsyncSession, file_path: str, current_session_id: str, cwd: str
) -> str | None:
    """Returns a warning string if another session recently edited the file, else None."""
    result = await db.execute(
        text(FILE_LOCK_QUERY),
        {
            "target_file_path": file_path,
            "current_session_id": current_session_id,
            "staleness_sec": settings.FILE_LOCK_STALENESS_SEC,
        },
    )
    row = result.first()
    if row:
        minutes_ago = (datetime.now(UTC) - row.created_at.replace(tzinfo=UTC)).total_seconds() / 60
        return (
            f"Warning: {file_path} was edited {minutes_ago:.0f} minutes ago "
            f"by session {row.cc_session_id} which is still active. "
            f"Proceed with caution — your changes may conflict."
        )
    return None
