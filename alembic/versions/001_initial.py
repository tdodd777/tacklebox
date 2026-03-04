"""Initial schema - all 6 tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("cc_session_id", sa.Text(), nullable=False, unique=True),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False, server_default="startup"),
        sa.Column("permission_mode", sa.Text(), nullable=False, server_default="default"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("end_reason", sa.Text()),
        sa.CheckConstraint("source IN ('startup','resume','clear','compact')", name="ck_sessions_source"),
        sa.CheckConstraint("status IN ('active','completed','interrupted')", name="ck_sessions_status"),
    )
    op.create_index("idx_sessions_status", "sessions", ["status"])
    op.create_index("idx_sessions_cwd", "sessions", ["cwd"])

    # tool_events
    op.create_table(
        "tool_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("hook_event", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_input", postgresql.JSONB()),
        sa.Column("tool_response", postgresql.JSONB()),
        sa.Column("tool_use_id", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("decision", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_tool_events_session", "tool_events", ["session_id"])
    op.create_index("idx_tool_events_tool", "tool_events", ["tool_name"])
    op.create_index("idx_tool_events_time", "tool_events", ["created_at"])

    # session_context
    op.create_table(
        "session_context",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="project"),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("scope IN ('session','project')", name="ck_session_context_scope"),
    )
    op.create_index(
        "idx_ctx_project_key",
        "session_context",
        ["cwd", "key"],
        unique=True,
        postgresql_where=sa.text("scope = 'project'"),
    )

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # subagent_events
    op.create_table(
        "subagent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("hook_event", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("agent_type", sa.Text(), nullable=False),
        sa.Column("agent_transcript_path", sa.Text()),
        sa.Column("last_assistant_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("hook_event IN ('SubagentStart','SubagentStop')", name="ck_subagent_events_hook"),
    )
    op.create_index("idx_subagent_events_session", "subagent_events", ["session_id"])
    op.create_index("idx_subagent_events_agent", "subagent_events", ["agent_id"])

    # stop_blocks
    op.create_table(
        "stop_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_stop_blocks_session", "stop_blocks", ["session_id"])


def downgrade() -> None:
    op.drop_table("stop_blocks")
    op.drop_table("subagent_events")
    op.drop_table("notifications")
    op.drop_table("session_context")
    op.drop_table("tool_events")
    op.drop_table("sessions")
