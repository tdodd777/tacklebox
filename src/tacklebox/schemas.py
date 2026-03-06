from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Enums ---

class PermissionMode(str, Enum):
    default = "default"
    plan = "plan"
    accept_edits = "acceptEdits"
    dont_ask = "dontAsk"
    bypass_permissions = "bypassPermissions"


class SessionSource(str, Enum):
    startup = "startup"
    resume = "resume"
    clear = "clear"
    compact = "compact"


# --- Base Input ---

class HookInput(BaseModel):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: PermissionMode
    hook_event_name: str


# --- Event Input Models ---

class SessionStartInput(HookInput):
    source: SessionSource
    model: str
    agent_type: Optional[str] = None


class SessionEndInput(HookInput):
    reason: str = ""


class PreToolUseInput(HookInput):
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


class PostToolUseInput(HookInput):
    tool_name: str
    tool_input: dict[str, Any]
    tool_response: dict[str, Any]
    tool_use_id: str


class PostToolUseFailureInput(HookInput):
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    error: str
    is_interrupt: bool = False


class PermissionRequestInput(HookInput):
    tool_name: str
    tool_input: dict[str, Any]
    permission_suggestions: list[dict[str, Any]] = Field(default_factory=list)


class UserPromptSubmitInput(HookInput):
    prompt: str


class StopInput(HookInput):
    stop_hook_active: bool = False
    last_assistant_message: str = ""


class SubagentStartInput(HookInput):
    agent_id: str
    agent_type: str


class SubagentStopInput(HookInput):
    stop_hook_active: bool = False
    agent_id: str
    agent_type: str
    agent_transcript_path: str = ""
    last_assistant_message: str = ""


class NotificationInput(HookInput):
    notification_type: str
    message: str = ""
    title: Optional[str] = None


class PreCompactInput(HookInput):
    trigger: str
    custom_instructions: str = ""


class TeammateIdleInput(HookInput):
    teammate_name: str
    team_name: str


class TaskCompletedInput(HookInput):
    task_id: str
    task_subject: str
    task_description: Optional[str] = None
    teammate_name: Optional[str] = None
    team_name: Optional[str] = None


# --- Response Models ---

class HookResponse(BaseModel):
    continue_session: Optional[bool] = Field(None, alias="continue")
    stopReason: Optional[str] = None
    suppressOutput: Optional[bool] = None
    systemMessage: Optional[str] = None

    model_config = {"populate_by_name": True}


# SessionStart
class SessionStartSpecific(BaseModel):
    hookEventName: str = "SessionStart"
    additionalContext: Optional[str] = None


class SessionStartResponse(HookResponse):
    hookSpecificOutput: Optional[SessionStartSpecific] = None


# PreToolUse
class PreToolUseSpecific(BaseModel):
    hookEventName: str = "PreToolUse"
    permissionDecision: Optional[str] = None
    permissionDecisionReason: Optional[str] = None
    updatedInput: Optional[dict[str, Any]] = None
    additionalContext: Optional[str] = None


class PreToolUseResponse(HookResponse):
    hookSpecificOutput: Optional[PreToolUseSpecific] = None


# PermissionRequest
class PermissionDecision(BaseModel):
    behavior: str
    updatedInput: Optional[dict[str, Any]] = None
    updatedPermissions: Optional[list[dict[str, Any]]] = None
    message: Optional[str] = None
    interrupt: Optional[bool] = None


class PermissionRequestSpecific(BaseModel):
    hookEventName: str = "PermissionRequest"
    decision: Optional[PermissionDecision] = None


class PermissionRequestResponse(HookResponse):
    hookSpecificOutput: Optional[PermissionRequestSpecific] = None


# PostToolUse
class PostToolUseSpecific(BaseModel):
    hookEventName: str = "PostToolUse"
    additionalContext: Optional[str] = None
    updatedMCPToolOutput: Optional[Any] = None


class PostToolUseResponse(HookResponse):
    decision: Optional[str] = None
    reason: Optional[str] = None
    hookSpecificOutput: Optional[PostToolUseSpecific] = None


# PostToolUseFailure
class PostToolUseFailureSpecific(BaseModel):
    hookEventName: str = "PostToolUseFailure"
    additionalContext: Optional[str] = None


class PostToolUseFailureResponse(HookResponse):
    hookSpecificOutput: Optional[PostToolUseFailureSpecific] = None


# Stop / SubagentStop
class StopResponse(HookResponse):
    decision: Optional[str] = None
    reason: Optional[str] = None


# UserPromptSubmit
class UserPromptSubmitSpecific(BaseModel):
    hookEventName: str = "UserPromptSubmit"
    additionalContext: Optional[str] = None


class UserPromptSubmitResponse(HookResponse):
    decision: Optional[str] = None
    reason: Optional[str] = None
    hookSpecificOutput: Optional[UserPromptSubmitSpecific] = None


# SubagentStart
class SubagentStartSpecific(BaseModel):
    hookEventName: str = "SubagentStart"
    additionalContext: Optional[str] = None


class SubagentStartResponse(HookResponse):
    hookSpecificOutput: Optional[SubagentStartSpecific] = None


# Empty (Notification, SessionEnd, PreCompact)
class EmptyResponse(HookResponse):
    pass
