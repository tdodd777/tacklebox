"""Add missing indexes for session context and notifications

Revision ID: 002
Revises: 001
Create Date: 2026-03-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial unique index for session-scoped context lookups
    op.create_index(
        "idx_ctx_session_key",
        "session_context",
        ["session_id", "key"],
        unique=True,
        postgresql_where=sa.text("scope = 'session'"),
    )

    # Notifications indexes for Grafana queries and session lookups
    op.create_index("idx_notifications_session", "notifications", ["session_id"])
    op.create_index("idx_notifications_time", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_notifications_time", table_name="notifications")
    op.drop_index("idx_notifications_session", table_name="notifications")
    op.drop_index("idx_ctx_session_key", table_name="session_context")
