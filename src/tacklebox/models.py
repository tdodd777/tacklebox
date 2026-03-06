import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    cc_session_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    cwd: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="startup"
    )
    permission_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="default"
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "source IN ('startup','resume','clear','compact')", name="ck_sessions_source"
        ),
        CheckConstraint(
            "status IN ('active','completed','interrupted')", name="ck_sessions_status"
        ),
        Index("idx_sessions_status", "status"),
        Index("idx_sessions_cwd", "cwd"),
    )


class ToolEvent(Base):
    __tablename__ = "tool_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    hook_event: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_input: Mapped[dict | None] = mapped_column(JSONB)
    tool_response: Mapped[dict | None] = mapped_column(JSONB)
    tool_use_id: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_tool_events_session", "session_id"),
        Index("idx_tool_events_tool", "tool_name"),
        Index("idx_tool_events_time", "created_at"),
    )


class SessionContext(Base):
    __tablename__ = "session_context"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    cwd: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="project"
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('session','project')", name="ck_session_context_scope"
        ),
        Index(
            "idx_ctx_project_key",
            "cwd",
            "key",
            unique=True,
            postgresql_where=text("scope = 'project'"),
        ),
        Index(
            "idx_ctx_session_key",
            "session_id",
            "key",
            unique=True,
            postgresql_where=text("scope = 'session'"),
        ),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_notifications_session", "session_id"),
        Index("idx_notifications_time", "created_at"),
    )


class SubagentEvent(Base):
    __tablename__ = "subagent_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    hook_event: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    agent_transcript_path: Mapped[str | None] = mapped_column(Text)
    last_assistant_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "hook_event IN ('SubagentStart','SubagentStop')",
            name="ck_subagent_events_hook",
        ),
        Index("idx_subagent_events_session", "session_id"),
        Index("idx_subagent_events_agent", "agent_id"),
    )


class StopBlock(Base):
    __tablename__ = "stop_blocks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("idx_stop_blocks_session", "session_id"),)
