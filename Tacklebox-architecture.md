# Tacklebox

*Where you keep your hooks.*

*FastAPI + PostgreSQL + Grafana — Session coordination, context persistence, and audit logging for Claude Code*

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Hook Input/Output Reference](#3-hook-inputoutput-reference)
4. [Pydantic Schemas](#4-pydantic-schemas)
5. [Database Schema](#5-database-schema)
6. [Endpoint Handler Logic](#6-endpoint-handler-logic)
7. [Hook Configurations](#7-hook-configurations)
8. [Coordination Patterns](#8-coordination-patterns)
9. [Error Handling Strategy](#9-error-handling-strategy)
10. [Server Structure](#10-server-structure)
11. [Observability and Grafana Dashboards](#11-observability-and-grafana-dashboards)
12. [Testing Strategy](#12-testing-strategy)
13. [Security Considerations](#13-security-considerations)
14. [Setup Guide](#14-setup-guide)
15. [Next Steps](#15-next-steps)

---

## 1. Overview

This document defines the architecture for a persistent state server that sits between Claude Code sessions and a PostgreSQL database. The server receives hook events from Claude Code via native HTTP hooks, stores structured data, and returns context or control decisions back to Claude Code.

The system addresses three core problems:

- **Session coordination:** Multiple concurrent Claude Code sessions can see what each other is doing, avoid duplicate work, and hand off tasks.
- **Context persistence:** When a session starts or resumes, it can pull in relevant context from prior sessions, including decisions made, files changed, and errors encountered.
- **Audit and observability:** Every tool invocation, permission decision, and session lifecycle event is logged with full metadata for analysis and debugging.

---

## 2. System Architecture

### 2.1 Component Overview

The system consists of three layers:

- **Native HTTP hooks:** Claude Code supports `"type": "http"` hooks that POST event JSON directly to a URL. No shell scripts, curl commands, or stdin piping required. Claude Code sends the hook input as the POST request body with `Content-Type: application/json` and reads the response body for decisions.
- **State server:** A FastAPI application running on localhost that receives hook events, queries and writes to PostgreSQL, and returns structured JSON responses conforming to Claude Code's per-event output schemas.
- **PostgreSQL database:** Stores sessions, tool events, shared context, and session key-value state. Provides the persistence and query capabilities that file-based approaches lack.

### 2.2 Data Flow

The lifecycle of a hook event follows this path:

1. Claude Code fires a hook event (e.g., SessionStart, PreToolUse, Stop).
2. The native HTTP hook POSTs the event JSON directly to the state server.
3. The state server parses the event into a typed Pydantic model, writes to PostgreSQL, and evaluates any coordination logic.
4. The server returns a JSON response conforming to Claude Code's hook output schema for that specific event type.
5. Claude Code processes the response (inject context, allow/deny tool use, block/allow stop).

If the server is unreachable or returns a non-2xx response, Claude Code treats it as a non-blocking error and the action proceeds. The system **fails open** by design.

### 2.3 Deployment Topology

For local development, the server and database both run on the same machine. The HTTP hooks target `http://localhost:8420`. For team or CI environments, the server can run on a shared host with TLS, and hook URLs target the remote address. The architecture is the same in both cases.

---

## 3. Hook Input/Output Reference

This section documents the actual field names and schemas that Claude Code uses. The server must parse these exact fields from incoming requests and return responses in the exact format each event type expects.

### 3.1 Common Input Fields

Every hook event receives these fields in the POST body:

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Current session identifier |
| `transcript_path` | string | Path to conversation JSONL file |
| `cwd` | string | Current working directory when the hook fires |
| `permission_mode` | string | One of: `default`, `plan`, `acceptEdits`, `dontAsk`, `bypassPermissions` |
| `hook_event_name` | string | Name of the event that fired |

**Important:** There is no `timestamp` field. The server must generate its own timestamps. The `cwd` field is the working directory, not necessarily the project root.

### 3.2 Event-Specific Input Fields

#### SessionStart

| Field | Type | Description |
|---|---|---|
| `source` | string | How the session started: `startup`, `resume`, `clear`, or `compact` |
| `model` | string | Model identifier (e.g., `claude-sonnet-4-6`) |
| `agent_type` | string | Present only when started with `claude --agent <name>` |

#### SessionEnd

| Field | Type | Description |
|---|---|---|
| `reason` | string | Why the session ended: `clear`, `logout`, `prompt_input_exit`, `bypass_permissions_disabled`, or `other` |

#### PreToolUse

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Tool name (e.g., `Bash`, `Write`, `Edit`, `Read`) |
| `tool_input` | object | Tool-specific parameters (e.g., `{ "command": "npm test" }` for Bash) |
| `tool_use_id` | string | Unique identifier for this tool invocation |

#### PostToolUse

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Tool name |
| `tool_input` | object | Tool parameters that were sent |
| `tool_response` | object | Tool result/output |
| `tool_use_id` | string | Unique identifier for this tool invocation |

#### PostToolUseFailure

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Tool name |
| `tool_input` | object | Tool parameters that were sent |
| `tool_use_id` | string | Unique identifier for this tool invocation |
| `error` | string | Description of what went wrong |
| `is_interrupt` | boolean | Whether the failure was caused by user interruption |

#### PermissionRequest

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Tool name |
| `tool_input` | object | Tool parameters |
| `permission_suggestions` | array | The "always allow" options the user would see in the permission dialog |

#### UserPromptSubmit

| Field | Type | Description |
|---|---|---|
| `prompt` | string | The text the user submitted |

#### Stop

| Field | Type | Description |
|---|---|---|
| `stop_hook_active` | boolean | `true` when Claude is already continuing due to a prior Stop hook block. **Must be checked to prevent infinite loops.** |
| `last_assistant_message` | string | Text content of Claude's final response |

#### SubagentStop

| Field | Type | Description |
|---|---|---|
| `stop_hook_active` | boolean | Same as Stop |
| `agent_id` | string | Unique identifier for the subagent |
| `agent_type` | string | Agent type name |
| `agent_transcript_path` | string | Path to the subagent's transcript |
| `last_assistant_message` | string | Subagent's final response text |

#### SubagentStart

| Field | Type | Description |
|---|---|---|
| `agent_id` | string | Unique identifier for the subagent |
| `agent_type` | string | Agent type name |

#### Notification

| Field | Type | Description |
|---|---|---|
| `notification_type` | string | Type: `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog` |
| `message` | string | Notification text |
| `title` | string | Optional notification title |

#### PreCompact

| Field | Type | Description |
|---|---|---|
| `trigger` | string | `manual` or `auto` |
| `custom_instructions` | string | User-provided compaction instructions (empty for auto) |

#### TeammateIdle

| Field | Type | Description |
|---|---|---|
| `teammate_name` | string | Name of the teammate going idle |
| `team_name` | string | Name of the team |

#### TaskCompleted

| Field | Type | Description |
|---|---|---|
| `task_id` | string | Task identifier |
| `task_subject` | string | Task title |
| `task_description` | string | Task details (may be absent) |
| `teammate_name` | string | Name of the completing teammate (may be absent) |
| `team_name` | string | Team name (may be absent) |

### 3.3 Output Schemas By Event

Each event type has a specific output format the server must return. Returning the wrong format causes Claude Code to ignore the response. The server must return valid JSON with a 2xx status code. Non-2xx responses are treated as non-blocking errors (the action proceeds).

#### Universal Fields (all events)

| Field | Default | Description |
|---|---|---|
| `continue` | `true` | If `false`, Claude stops entirely. Overrides all other decision fields |
| `stopReason` | — | Message shown to user when `continue` is `false` |
| `suppressOutput` | `false` | If `true`, hides stdout from verbose mode |
| `systemMessage` | — | Warning message shown to user |

#### SessionStart Response

Returns context for the new session. Any plain text in the response is also added as context.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Prior session edited api/routes.py and tests/test_routes.py. Last Bash command failed with exit code 1. Current sprint: auth refactor."
  }
}
```

#### PreToolUse Response

Uses `hookSpecificOutput` with three decision options. This is different from other events.

- `"allow"`: proceed without showing a permission prompt
- `"deny"`: cancel the tool call and send the reason to Claude
- `"ask"`: show the permission prompt to the user as normal

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "File is locked by another active session (session abc123)",
    "additionalContext": "Optional context injected before tool executes"
  }
}
```

To modify tool input before execution (e.g., rewrite a command):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "command": "npm test -- --bail"
    }
  }
}
```

#### PermissionRequest Response

Uses `hookSpecificOutput.decision.behavior`. Different structure from PreToolUse.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedInput": {
        "command": "npm run lint"
      }
    }
  }
}
```

To deny:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "deny",
      "message": "Destructive commands require manual approval"
    }
  }
}
```

#### PostToolUse Response

Uses top-level `decision: "block"` (omit `decision` to allow).

```json
{
  "decision": "block",
  "reason": "Lint errors detected in written file",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "Additional information for Claude"
  }
}
```

#### PostToolUseFailure Response

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUseFailure",
    "additionalContext": "This test failure is a known flaky test. Retry once before investigating."
  }
}
```

#### Stop / SubagentStop Response

Uses top-level `decision: "block"` to prevent stopping. **Must check `stop_hook_active` to prevent infinite loops.**

```json
{
  "decision": "block",
  "reason": "Task X is still incomplete. Tests are failing in auth module."
}
```

To allow the stop, return empty JSON `{}` or omit the `decision` field.

#### UserPromptSubmit Response

To inject context (non-blocking):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Relevant context from prior sessions"
  }
}
```

To block the prompt:

```json
{
  "decision": "block",
  "reason": "Prompt contains a potential secret (API key pattern detected)"
}
```

#### Notification, SessionEnd, SubagentStart, PreCompact

These events have **no decision control**. The server logs them and returns `{}`. For SubagentStart, you can return `additionalContext`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SubagentStart",
    "additionalContext": "Follow security guidelines for this task"
  }
}
```

#### TeammateIdle, TaskCompleted

These events use **exit codes only** for decision control (exit 2 blocks). Since we use HTTP hooks (not command hooks), these cannot be blocked via the server. They are logged for observability only.

---

## 4. Pydantic Schemas

These models go in `src/server/schemas.py`. They define the typed contract between Claude Code and the server, and are used directly by FastAPI for request validation and response serialization.

### 4.1 Base Input Model

```python
from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class PermissionMode(str, Enum):
    default = "default"
    plan = "plan"
    accept_edits = "acceptEdits"
    dont_ask = "dontAsk"
    bypass_permissions = "bypassPermissions"


class HookInput(BaseModel):
    """Common fields present in every hook event."""
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: PermissionMode
    hook_event_name: str
```

### 4.2 Event Input Models

```python
class SessionSource(str, Enum):
    startup = "startup"
    resume = "resume"
    clear = "clear"
    compact = "compact"


class SessionStartInput(HookInput):
    source: SessionSource
    model: str
    agent_type: Optional[str] = None


class SessionEndInput(HookInput):
    reason: str  # clear, logout, prompt_input_exit, bypass_permissions_disabled, other


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
    trigger: str  # manual or auto
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
```

### 4.3 Response Models

Each event type uses a specific response structure. Response models return `None` for optional fields so they are excluded from serialized JSON (using `model_dump(exclude_none=True)`).

```python
class HookResponse(BaseModel):
    """Universal fields available on all responses."""
    # Set continue_session to False to stop Claude entirely
    continue_session: Optional[bool] = Field(None, alias="continue")
    stopReason: Optional[str] = None
    suppressOutput: Optional[bool] = None
    systemMessage: Optional[str] = None

    model_config = {"populate_by_name": True}


# --- SessionStart ---

class SessionStartSpecific(BaseModel):
    hookEventName: str = "SessionStart"
    additionalContext: Optional[str] = None


class SessionStartResponse(HookResponse):
    hookSpecificOutput: Optional[SessionStartSpecific] = None


# --- PreToolUse ---

class PreToolUseSpecific(BaseModel):
    hookEventName: str = "PreToolUse"
    permissionDecision: Optional[str] = None   # allow, deny, ask
    permissionDecisionReason: Optional[str] = None
    updatedInput: Optional[dict[str, Any]] = None
    additionalContext: Optional[str] = None


class PreToolUseResponse(HookResponse):
    hookSpecificOutput: Optional[PreToolUseSpecific] = None


# --- PermissionRequest ---

class PermissionDecision(BaseModel):
    behavior: str  # allow or deny
    updatedInput: Optional[dict[str, Any]] = None
    updatedPermissions: Optional[list[dict[str, Any]]] = None
    message: Optional[str] = None
    interrupt: Optional[bool] = None


class PermissionRequestSpecific(BaseModel):
    hookEventName: str = "PermissionRequest"
    decision: Optional[PermissionDecision] = None


class PermissionRequestResponse(HookResponse):
    hookSpecificOutput: Optional[PermissionRequestSpecific] = None


# --- PostToolUse ---

class PostToolUseSpecific(BaseModel):
    hookEventName: str = "PostToolUse"
    additionalContext: Optional[str] = None
    updatedMCPToolOutput: Optional[Any] = None


class PostToolUseResponse(HookResponse):
    decision: Optional[str] = None  # "block" or omit
    reason: Optional[str] = None
    hookSpecificOutput: Optional[PostToolUseSpecific] = None


# --- PostToolUseFailure ---

class PostToolUseFailureSpecific(BaseModel):
    hookEventName: str = "PostToolUseFailure"
    additionalContext: Optional[str] = None


class PostToolUseFailureResponse(HookResponse):
    hookSpecificOutput: Optional[PostToolUseFailureSpecific] = None


# --- Stop / SubagentStop ---

class StopResponse(HookResponse):
    decision: Optional[str] = None  # "block" or omit
    reason: Optional[str] = None


# --- UserPromptSubmit ---

class UserPromptSubmitSpecific(BaseModel):
    hookEventName: str = "UserPromptSubmit"
    additionalContext: Optional[str] = None


class UserPromptSubmitResponse(HookResponse):
    decision: Optional[str] = None  # "block" or omit
    reason: Optional[str] = None
    hookSpecificOutput: Optional[UserPromptSubmitSpecific] = None


# --- SubagentStart ---

class SubagentStartSpecific(BaseModel):
    hookEventName: str = "SubagentStart"
    additionalContext: Optional[str] = None


class SubagentStartResponse(HookResponse):
    hookSpecificOutput: Optional[SubagentStartSpecific] = None


# --- Fire-and-forget events (Notification, SessionEnd, PreCompact) ---

class EmptyResponse(HookResponse):
    """For events with no decision control."""
    pass
```

### 4.4 Response Helper

A convenience function in `services/responses.py` serializes response models while stripping `None` values:

```python
from pydantic import BaseModel


def serialize_response(response: BaseModel) -> dict:
    """Serialize a response model, excluding None fields.

    Claude Code ignores unknown fields but may fail on malformed
    JSON, so we strip nulls to keep responses clean.
    """
    return response.model_dump(by_alias=True, exclude_none=True)
```

---

## 5. Database Schema

### 5.1 sessions

Tracks every Claude Code session from start to end. The `cwd` column stores the working directory from the hook input and allows filtering by project. The `source` column records how the session was initiated.

**Upsert semantics:** SessionStart uses `INSERT ... ON CONFLICT (cc_session_id) DO UPDATE` to handle the case where the same session fires SessionStart multiple times (e.g., after `/clear` or compaction). On conflict, the server updates `source`, `model`, `permission_mode`, and resets `status` to `active`.

**Stale session cleanup:** A background task runs every 5 minutes and marks sessions as `interrupted` if they have been `active` for longer than `SESSION_TIMEOUT_SEC` (default 4 hours) without any tool_events. This handles sessions that crashed without firing SessionEnd.

```sql
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cc_session_id   TEXT UNIQUE NOT NULL,
    cwd             TEXT NOT NULL,
    model           TEXT,
    source          TEXT NOT NULL DEFAULT 'startup'
                    CHECK (source IN ('startup','resume','clear','compact')),
    permission_mode TEXT NOT NULL DEFAULT 'default',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','completed','interrupted')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    end_reason      TEXT
);

CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_cwd    ON sessions(cwd);
```

### 5.2 tool_events

The primary audit log. Every PreToolUse, PostToolUse, PostToolUseFailure, and PermissionRequest event lands here. The `tool_input` and `tool_response` columns store the full JSON payloads, making it possible to replay or analyze exactly what happened. The `error` column captures failure details from PostToolUseFailure events.

```sql
CREATE TABLE tool_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    hook_event      TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_input      JSONB,
    tool_response   JSONB,
    tool_use_id     TEXT,
    error           TEXT,
    decision        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tool_events_session ON tool_events(session_id);
CREATE INDEX idx_tool_events_tool    ON tool_events(tool_name);
CREATE INDEX idx_tool_events_time    ON tool_events(created_at);
```

### 5.3 session_context

A key-value store scoped to either a specific session or a project. This is where sessions persist state that other sessions (or resumed sessions) can read. The `scope` column determines visibility: `session` means only the originating session can read it, while `project` means any session in the same `cwd` can access it.

```sql
CREATE TABLE session_context (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    cwd             TEXT NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'project'
                    CHECK (scope IN ('session','project')),
    key             TEXT NOT NULL,
    value           JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_ctx_project_key
    ON session_context(cwd, key)
    WHERE scope = 'project';
```

### 5.4 notifications

Stores notification events for observability. Useful for tracking how often Claude requests permissions, how long idle periods last, and whether sessions are getting stuck.

```sql
CREATE TABLE notifications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID NOT NULL REFERENCES sessions(id),
    notification_type TEXT NOT NULL,
    title             TEXT,
    message           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 5.5 subagent_events

Tracks subagent lifecycle for multi-session coordination.

```sql
CREATE TABLE subagent_events (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            UUID NOT NULL REFERENCES sessions(id),
    hook_event            TEXT NOT NULL CHECK (hook_event IN ('SubagentStart','SubagentStop')),
    agent_id              TEXT NOT NULL,
    agent_type            TEXT NOT NULL,
    agent_transcript_path TEXT,
    last_assistant_message TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_subagent_events_session ON subagent_events(session_id);
CREATE INDEX idx_subagent_events_agent   ON subagent_events(agent_id);
```

### 5.6 stop_blocks

Tracks how many times the Stop hook has blocked a given session from stopping. Used to enforce `STOP_MAX_BLOCKS` and prevent infinite loops.

```sql
CREATE TABLE stop_blocks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id),
    reason      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_stop_blocks_session ON stop_blocks(session_id);
```

---

## 6. Endpoint Handler Logic

This section defines the step-by-step logic for each hook endpoint. Every handler follows the same outer pattern: parse input, resolve the session, execute event-specific logic inside a fail-open wrapper (see section 9), and return the typed response.

### 6.1 POST /hooks/session-start

**Input model:** `SessionStartInput`
**Response model:** `SessionStartResponse`

```
1. Parse request body as SessionStartInput
2. Upsert into sessions table:
     INSERT INTO sessions (cc_session_id, cwd, model, source, permission_mode, status)
     VALUES ($session_id, $cwd, $model, $source, $permission_mode, 'active')
     ON CONFLICT (cc_session_id)
     DO UPDATE SET source = $source, model = $model, permission_mode = $permission_mode,
                   status = 'active', started_at = now(), ended_at = NULL
     RETURNING id
3. Build activity summary (see section 8.3 for template):
   a. Query project-scoped context keys for this cwd
   b. If source is 'resume' or 'compact':
      - Query the N most recent tool_events for this session (CONTEXT_SUMMARY_LIMIT)
      - Extract distinct file paths from Write/Edit tool_input
      - Find last Bash result and its exit status
      - Build summary string
   c. If source is 'startup':
      - Query only project-scoped context (no session-specific history)
4. Return SessionStartResponse with additionalContext
```

### 6.2 POST /hooks/session-end

**Input model:** `SessionEndInput`
**Response model:** `EmptyResponse`

```
1. Parse request body as SessionEndInput
2. Look up session by cc_session_id:
     SELECT id FROM sessions WHERE cc_session_id = $session_id
   If not found, log warning and return {}
3. Update session:
     UPDATE sessions SET status = 'completed', ended_at = now(), end_reason = $reason
     WHERE cc_session_id = $session_id
4. Return {}
```

### 6.3 POST /hooks/pre-tool-use

**Input model:** `PreToolUseInput`
**Response model:** `PreToolUseResponse`

```
1. Parse request body as PreToolUseInput
2. Resolve session_id → internal UUID (cached per request)
3. Insert into tool_events:
     (session_id, hook_event='PreToolUse', tool_name, tool_input, tool_use_id)
4. If tool_name is 'Write' or 'Edit':
   a. Extract file_path from tool_input.file_path
   b. Run file lock detection query (see section 8.1)
   c. If conflict found:
      - Update tool_events.decision = 'warn'
      - Return PreToolUseResponse with permissionDecision='allow'
        and additionalContext warning about the concurrent edit
5. Return PreToolUseResponse with no permissionDecision (allow by default)
```

### 6.4 POST /hooks/post-tool-use

**Input model:** `PostToolUseInput`
**Response model:** `PostToolUseResponse`

```
1. Parse request body as PostToolUseInput
2. Resolve session_id → internal UUID
3. Insert into tool_events:
     (session_id, hook_event='PostToolUse', tool_name, tool_input, tool_response, tool_use_id)
4. If tool_name is 'Write' or 'Edit':
   a. Upsert project-scoped context key 'last_edited_files':
      - Append tool_input.file_path to the list
      - Keep last 20 entries
5. If tool_name is 'Bash':
   a. Store tool_input.command and exit status in session-scoped context
      key 'last_bash_result'
6. Return {} (no blocking decisions for PostToolUse in default config)
```

### 6.5 POST /hooks/post-tool-use-failure

**Input model:** `PostToolUseFailureInput`
**Response model:** `PostToolUseFailureResponse`

```
1. Parse request body as PostToolUseFailureInput
2. Resolve session_id → internal UUID
3. Insert into tool_events:
     (session_id, hook_event='PostToolUseFailure', tool_name, tool_input,
      tool_use_id, error)
4. Return {}
```

### 6.6 POST /hooks/permission-request

**Input model:** `PermissionRequestInput`
**Response model:** `PermissionRequestResponse`

```
1. Parse request body as PermissionRequestInput
2. Resolve session_id → internal UUID
3. Insert into tool_events:
     (session_id, hook_event='PermissionRequest', tool_name, tool_input)
4. Return {} (log only — no auto-approve/deny by default)
```

### 6.7 POST /hooks/user-prompt

**Input model:** `UserPromptSubmitInput`
**Response model:** `UserPromptSubmitResponse`

```
1. Parse request body as UserPromptSubmitInput
2. Resolve session_id → internal UUID
3. (Optional) Log the prompt text for audit — consider privacy implications.
   By default, log only a hash or the character count, not the full prompt.
4. Return {} (no blocking or context injection by default)
```

### 6.8 POST /hooks/stop

**Input model:** `StopInput`
**Response model:** `StopResponse`

This is the most complex handler due to infinite-loop prevention.

```
1. Parse request body as StopInput
2. Resolve session_id → internal UUID
3. If stop_hook_active is true:
   a. Count rows in stop_blocks for this session_id
   b. If count >= STOP_MAX_BLOCKS:
      - Return {} (allow stop — safety valve)
4. Check session_context for incomplete tasks:
     SELECT value FROM session_context
     WHERE cwd = $cwd AND scope = 'project' AND key = 'incomplete_tasks'
5. If incomplete tasks exist:
   a. Insert into stop_blocks (session_id, reason)
   b. Return StopResponse(decision="block", reason="Tasks still incomplete: ...")
6. Return {} (allow stop)
```

### 6.9 POST /hooks/notification

**Input model:** `NotificationInput`
**Response model:** `EmptyResponse`

```
1. Parse request body as NotificationInput
2. Resolve session_id → internal UUID
3. Insert into notifications:
     (session_id, notification_type, title, message)
4. Return {}
```

### 6.10 POST /hooks/subagent-start

**Input model:** `SubagentStartInput`
**Response model:** `SubagentStartResponse`

```
1. Parse request body as SubagentStartInput
2. Resolve session_id → internal UUID
3. Insert into subagent_events:
     (session_id, hook_event='SubagentStart', agent_id, agent_type)
4. Query project-scoped context for this cwd
5. If context exists, return SubagentStartResponse with additionalContext
6. Otherwise return {}
```

### 6.11 POST /hooks/subagent-stop

**Input model:** `SubagentStopInput`
**Response model:** `StopResponse`

```
1. Parse request body as SubagentStopInput
2. Resolve session_id → internal UUID
3. Insert into subagent_events:
     (session_id, hook_event='SubagentStop', agent_id, agent_type,
      agent_transcript_path, last_assistant_message)
4. Apply same stop_hook_active / STOP_MAX_BLOCKS logic as Stop handler
5. Return StopResponse or {}
```

### 6.12 POST /hooks/pre-compact

**Input model:** `PreCompactInput`
**Response model:** `EmptyResponse`

```
1. Parse request body as PreCompactInput
2. Resolve session_id → internal UUID
3. Snapshot current session state into session_context:
   a. Query last 5 Write/Edit file paths from tool_events for this session
   b. Query last Bash result from session-scoped context
   c. Upsert project-scoped key 'pre_compact_snapshot' with this data
4. Return {}
```

### 6.13 Session Resolution Helper

Every handler needs to map `session_id` (the Claude Code string) to the internal UUID. This is a shared helper:

```python
from functools import lru_cache
from sqlalchemy import select
from .models import Session

async def resolve_session(db, cc_session_id: str, cwd: str) -> uuid.UUID | None:
    """Look up or create the internal session ID.

    If SessionStart hasn't fired yet (e.g., the server restarted mid-session),
    auto-create a session row to avoid losing events.
    """
    result = await db.execute(
        select(Session.id).where(Session.cc_session_id == cc_session_id)
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    # Auto-create if missing (fail-open: don't reject events)
    new_session = Session(
        cc_session_id=cc_session_id,
        cwd=cwd,
        source="startup",
        status="active",
    )
    db.add(new_session)
    await db.flush()
    return new_session.id
```

---

## 7. Hook Configurations

These configurations go in `.claude/settings.json` (project) or `~/.claude/settings.json` (user). All hooks use the native `"type": "http"` handler, which POSTs the event JSON directly to the server and reads the response body. No shell commands or curl piping required.

### 7.1 Full Settings Block

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/session-start",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/session-end",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/pre-tool-use",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/post-tool-use",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUseFailure": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/post-tool-use-failure",
            "timeout": 5
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/permission-request",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/user-prompt",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/stop",
            "timeout": 10
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/subagent-start",
            "timeout": 5
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/subagent-stop",
            "timeout": 10
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/notification",
            "timeout": 5
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/pre-compact",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### 7.2 Configuration Notes

- **Native HTTP hooks:** `"type": "http"` sends the event JSON as the POST body with `Content-Type: application/json` and reads the response body for decisions. No shell commands, stdin piping, or curl needed.
- **Error handling:** Non-2xx responses, connection failures, and timeouts are all treated as non-blocking errors — the action proceeds. To block a tool call or deny a permission, the server must return a 2xx response with the appropriate decision JSON.
- **Timeouts:** Defaults are 600 seconds for command hooks, 30 seconds for prompt hooks, 60 seconds for agent hooks. We set explicit short timeouts (5-10s) to keep Claude responsive.
- **PreToolUse matcher:** Scoped to `Write|Edit|Bash` for coordination checks on state-changing operations. Using `*` would send every Read, Glob, and Grep call to the server, adding unnecessary latency. Expand the matcher if you need to audit read operations.
- **PostToolUse matcher:** Also scoped to `Write|Edit|Bash` for the same reason.
- **PostToolUseFailure matcher:** Scoped to `Bash` since command failures are the most actionable. Expand to `*` for full coverage.
- **UserPromptSubmit:** Does **not** support matchers (the field is silently ignored). The hook always fires on every prompt submission.
- **Notification:** Has no decision control. The server logs and returns `{}`. Non-2xx responses are non-blocking.
- **SubagentStart:** Cannot block subagent creation but can inject context into the subagent via `additionalContext`.

### 7.3 Combining HTTP Hooks with Prompt Hooks

For nuanced decisions that require LLM judgment, you can add a `"type": "prompt"` hook alongside the HTTP hook for the same event. Both run in parallel. The HTTP hook handles deterministic rules from the database, while the prompt hook evaluates the conversation context.

Example: a Stop event with both a server check and an LLM evaluation:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8420/hooks/stop",
            "timeout": 10
          },
          {
            "type": "prompt",
            "prompt": "Check if all user-requested tasks are complete based on the conversation. If not, respond with { \"ok\": false, \"reason\": \"what remains\" }. Context: $ARGUMENTS",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

The prompt hook returns `{ "ok": true }` or `{ "ok": false, "reason": "..." }`. If either hook blocks, Claude continues.

---

## 8. Coordination Patterns

### 8.1 File Lock Detection

When a PreToolUse event arrives for a Write or Edit tool, the server checks whether another active session has recently written to the same file. The system **warns but does not block** — Claude receives context about the conflict and can decide how to proceed.

#### Path Extraction

File paths are extracted from `tool_input` based on tool type:

| Tool | Path field | Example |
|---|---|---|
| Write | `tool_input["file_path"]` | `"/home/user/project/src/api.py"` |
| Edit | `tool_input["file_path"]` | `"/home/user/project/src/api.py"` |
| Bash | Not directly available | Must parse `tool_input["command"]` — unreliable, so Bash is excluded from file lock checks |

File lock detection only applies to Write and Edit tools, where the path is an explicit, reliable field.

#### Detection Query

```sql
-- Find recent Write/Edit events to the same file from OTHER active sessions
SELECT
    s.cc_session_id,
    te.created_at,
    te.tool_name
FROM tool_events te
JOIN sessions s ON s.id = te.session_id
WHERE te.hook_event = 'PostToolUse'
  AND te.tool_name IN ('Write', 'Edit')
  AND te.tool_input->>'file_path' = $target_file_path
  AND s.cc_session_id != $current_session_id
  AND s.status = 'active'
  AND te.created_at > now() - make_interval(secs => $FILE_LOCK_STALENESS_SEC)
ORDER BY te.created_at DESC
LIMIT 1;
```

#### Response (Warn Only)

If a conflict is found, return a warning via `additionalContext`:

```python
async def check_file_lock(
    db, file_path: str, current_session_id: str, cwd: str
) -> str | None:
    """Returns a warning string if another session recently edited the file, else None."""
    result = await db.execute(text(FILE_LOCK_QUERY), {
        "target_file_path": file_path,
        "current_session_id": current_session_id,
        "FILE_LOCK_STALENESS_SEC": settings.FILE_LOCK_STALENESS_SEC,
    })
    row = result.first()
    if row:
        minutes_ago = (datetime.now(UTC) - row.created_at).total_seconds() / 60
        return (
            f"Warning: {file_path} was edited {minutes_ago:.0f} minutes ago "
            f"by session {row.cc_session_id} which is still active. "
            f"Proceed with caution — your changes may conflict."
        )
    return None
```

The PreToolUse handler incorporates this:

```python
if tool_name in ("Write", "Edit"):
    file_path = tool_input.get("file_path")
    if file_path:
        warning = await check_file_lock(db, file_path, session_id, cwd)
        if warning:
            return PreToolUseResponse(
                hookSpecificOutput=PreToolUseSpecific(
                    permissionDecision="allow",
                    additionalContext=warning,
                )
            )
```

### 8.2 Task Deduplication

When sessions are spawned to work on related tasks, the Stop hook can check the `session_context` table for a project-scoped key like `incomplete_tasks`. If the current session's task is already marked as done by another session, the Stop hook allows the stop. If not, it blocks the stop.

**Critical:** The Stop handler must check `stop_hook_active` from the input and enforce `STOP_MAX_BLOCKS` to prevent infinite loops. See section 6.8 for the full handler flow.

```python
async def handle_stop(db, event: StopInput, internal_session_id: uuid.UUID):
    # Safety valve: check block count
    if event.stop_hook_active:
        block_count = await db.scalar(
            select(func.count()).where(StopBlock.session_id == internal_session_id)
        )
        if block_count >= settings.STOP_MAX_BLOCKS:
            return StopResponse()  # allow stop

    # Check for incomplete tasks
    ctx = await db.execute(
        select(SessionContext.value)
        .where(SessionContext.cwd == event.cwd)
        .where(SessionContext.scope == "project")
        .where(SessionContext.key == "incomplete_tasks")
    )
    row = ctx.scalar_one_or_none()
    if row and row:  # non-empty list
        # Record the block
        db.add(StopBlock(session_id=internal_session_id, reason=str(row)))
        await db.flush()
        return StopResponse(
            decision="block",
            reason=f"Tasks still incomplete: {', '.join(row)}"
        )

    return StopResponse()  # allow stop
```

### 8.3 Context Injection on Resume

The SessionStart hook builds an activity summary from the database and returns it as `additionalContext`. The summary is factual and compact — recent files edited, last command results, and any project-scoped context keys.

#### Summary Builder

```python
async def build_session_summary(
    db, cwd: str, cc_session_id: str, source: str
) -> str | None:
    """Build an activity summary for context injection.

    Returns None if there's nothing useful to inject.
    """
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
            files = await db.execute(text("""
                SELECT DISTINCT tool_input->>'file_path' as file_path
                FROM tool_events
                WHERE session_id = :sid
                  AND tool_name IN ('Write', 'Edit')
                  AND hook_event = 'PostToolUse'
                ORDER BY file_path
                LIMIT 10
            """), {"sid": sid})
            file_list = [r.file_path for r in files if r.file_path]
            if file_list:
                parts.append(f"[files edited] {', '.join(file_list)}")

            # Last Bash command and result
            last_bash = await db.execute(text("""
                SELECT tool_input->>'command' as cmd,
                       tool_response->>'exitCode' as exit_code
                FROM tool_events
                WHERE session_id = :sid
                  AND tool_name = 'Bash'
                  AND hook_event = 'PostToolUse'
                ORDER BY created_at DESC
                LIMIT 1
            """), {"sid": sid})
            bash_row = last_bash.first()
            if bash_row:
                status = "succeeded" if bash_row.exit_code == "0" else f"failed (exit {bash_row.exit_code})"
                parts.append(f"[last command] `{bash_row.cmd}` {status}")

            # Recent failures
            failure_count = await db.scalar(text("""
                SELECT count(*) FROM tool_events
                WHERE session_id = :sid
                  AND hook_event = 'PostToolUseFailure'
                  AND created_at > now() - interval '1 hour'
            """), {"sid": sid})
            if failure_count and failure_count > 0:
                parts.append(f"[failures] {failure_count} tool failures in the last hour")

    # 3. Other active sessions in same cwd
    other_sessions = await db.scalar(text("""
        SELECT count(*) FROM sessions
        WHERE cwd = :cwd AND status = 'active' AND cc_session_id != :sid
    """), {"cwd": cwd, "sid": cc_session_id})
    if other_sessions and other_sessions > 0:
        parts.append(f"[coordination] {other_sessions} other active session(s) in this project")

    if not parts:
        return None

    return "\n".join(parts)
```

This produces output like:

```
[context] last_edited_files: ["src/api.py", "tests/test_api.py"]
[files edited] src/api.py, tests/test_api.py
[last command] `npm test` failed (exit 1)
[failures] 3 tool failures in the last hour
[coordination] 1 other active session(s) in this project
```

### 8.4 Intelligent Stop via Prompt Hook

For more nuanced stop decisions, combine the HTTP-based Stop hook (which consults the DB for hard rules) with a `"type": "prompt"` hook that evaluates the conversation context. Both hooks run in parallel within the same matcher group.

The HTTP hook handles deterministic rules (e.g., "block count not exceeded, incomplete tasks in DB"), while the prompt hook handles soft judgments (e.g., "the user asked for three things and only two are done"). If either hook blocks the stop, Claude continues.

See section 7.3 for the combined configuration example.

### 8.5 Subagent Coordination

SubagentStart and SubagentStop hooks enable tracking of multi-agent workflows. When a subagent starts, the server logs it and can inject project context. When a subagent finishes, the server records its final message and can extract completed-task information.

The SubagentStop handler follows the same `stop_hook_active` / `STOP_MAX_BLOCKS` guard pattern as the Stop handler.

### 8.6 Pre-Compaction Context Preservation

The PreCompact hook fires before Claude's context window is compressed. The server snapshots the current session's key state into `session_context`, ensuring that the SessionStart `compact` handler can re-inject the most important information after compaction completes.

The snapshot includes:
- Last 5 file paths edited (from tool_events)
- Last Bash command and its result
- Any session-scoped context keys

---

## 9. Error Handling Strategy

The system **fails open**: if anything goes wrong inside the server, Claude Code is never blocked. This is critical because a stuck hook directly blocks the user's workflow.

### 9.1 Fail-Open Wrapper

Every endpoint handler is wrapped in a try/except that catches all exceptions and returns an empty `{}` response (which Claude Code interprets as "proceed"):

```python
import logging
import traceback
from functools import wraps
from fastapi import Response

logger = logging.getLogger("tacklebox")


def fail_open(handler):
    """Decorator that ensures any unhandled exception returns {} with 200.

    This is the most important pattern in the server. A 500 response or
    a timeout means Claude Code proceeds without the hook's input, but
    a 200 with {} explicitly tells Claude Code to proceed. Both are
    non-blocking, but the latter is cleaner in logs.
    """
    @wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except Exception:
            logger.error(
                f"Handler {handler.__name__} failed, returning empty response:\n"
                f"{traceback.format_exc()}"
            )
            return {}
    return wrapper
```

Usage on every route:

```python
@router.post("/hooks/pre-tool-use")
@fail_open
async def pre_tool_use(event: PreToolUseInput, db: AsyncSession = Depends(get_db)):
    # ... handler logic ...
```

### 9.2 Database Unavailable

If the database connection fails, the fail-open wrapper catches the exception and returns `{}`. To provide faster feedback (rather than waiting for a connection timeout), the server checks the DB pool health on startup and logs warnings:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check DB connectivity on startup
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.warning(f"Database unavailable at startup: {e}. Hooks will fail open.")
    yield
    await engine.dispose()
```

### 9.3 Error Logging

Errors are logged to a local file for debugging. The log includes:
- The handler that failed
- The full exception traceback
- The event type and session ID (from the input, not the DB)

The log file path is configurable via `LOG_FILE` (default: `~/.local/share/tacklebox/server.log`).

### 9.4 What Can Go Wrong

| Failure | Impact | Behavior |
|---|---|---|
| Server not running | All hooks time out | Claude proceeds normally (non-blocking timeout) |
| Database down | All handlers throw | Fail-open wrapper returns `{}`, Claude proceeds |
| Slow query | Handler exceeds timeout | Claude proceeds (HTTP timeout in settings) |
| Invalid input JSON | Pydantic validation fails | FastAPI returns 422, Claude treats as non-blocking error |
| Session not found | `resolve_session` auto-creates it | Event is still logged |
| Schema migration pending | Columns may be missing | Fail-open catches the DB error |

---

## 10. Server Structure

### 10.1 Project Layout

```
tacklebox/
  pyproject.toml
  alembic.ini
  docker-compose.yml        # PostgreSQL + Grafana for local dev
  .env.example              # Template for environment variables
  alembic/
    env.py
    versions/
      001_initial.py
  src/
    tacklebox/
      __init__.py
      main.py               # FastAPI app, lifespan, middleware, fail_open decorator
      config.py             # Settings via pydantic-settings
      db.py                 # Async SQLAlchemy engine + session factory
      models.py             # SQLAlchemy ORM models
      schemas.py            # Pydantic models (section 4)
      routes/
        __init__.py
        hooks.py            # POST /hooks/* endpoints (section 6)
        sessions.py         # GET /sessions, /sessions/{id}/events
        context.py          # GET/PUT /context
      services/
        coordination.py     # File lock detection (section 8.1)
        context.py          # Context build + read/write (section 8.3)
        audit.py            # Event logging to tool_events, notifications, etc.
        responses.py        # serialize_response helper (section 4.4)
  tests/
    conftest.py             # Fixtures: test DB, FastAPI TestClient
    test_session_lifecycle.py
    test_pre_tool_use.py
    test_stop_handler.py
    test_context_injection.py
    test_file_lock.py
  grafana/
    provisioning/
      datasources/
        postgres.yml        # Auto-configure PostgreSQL datasource
      dashboards/
        dashboard.yml       # Auto-load dashboard JSON
    dashboards/
      tacklebox.json        # Main dashboard definition
```

### 10.2 Key Dependencies

| Package | Purpose |
|---|---|
| fastapi | HTTP framework |
| uvicorn | ASGI server |
| sqlalchemy[asyncio] | Async ORM and query builder |
| asyncpg | Async PostgreSQL driver |
| alembic | Schema migrations |
| pydantic-settings | Configuration from environment variables |
| httpx | Test client for pytest |

### 10.3 Configuration

The server reads configuration from environment variables with sensible defaults for local development:

| Variable | Default | Description |
|---|---|---|
| DATABASE_URL | postgresql+asyncpg://localhost/tacklebox | Async connection string |
| HOST | 127.0.0.1 | Bind address |
| PORT | 8420 | Bind port |
| FILE_LOCK_STALENESS_SEC | 300 | Window for file conflict detection |
| CONTEXT_SUMMARY_LIMIT | 20 | Max recent events to summarize on SessionStart |
| STOP_MAX_BLOCKS | 3 | Max times the Stop hook can block before allowing stop |
| SESSION_TIMEOUT_SEC | 14400 | Mark sessions as interrupted after this idle time (4 hours) |
| LOG_FILE | ~/.local/share/tacklebox/server.log | Error log location |
| LOG_LEVEL | INFO | Logging level |

### 10.4 Background Tasks

The server runs one background task via FastAPI's lifespan:

**Stale session cleanup** (every 5 minutes): marks sessions as `interrupted` if they have been `active` for longer than `SESSION_TIMEOUT_SEC` without any new `tool_events`:

```python
async def cleanup_stale_sessions(db_session_factory):
    while True:
        await asyncio.sleep(300)
        try:
            async with db_session_factory() as db:
                await db.execute(text("""
                    UPDATE sessions SET status = 'interrupted', ended_at = now()
                    WHERE status = 'active'
                      AND id NOT IN (
                          SELECT DISTINCT session_id FROM tool_events
                          WHERE created_at > now() - make_interval(secs => :timeout)
                      )
                      AND started_at < now() - make_interval(secs => :timeout)
                """), {"timeout": settings.SESSION_TIMEOUT_SEC})
                await db.commit()
        except Exception:
            logger.error(f"Stale session cleanup failed:\n{traceback.format_exc()}")
```

---

## 11. Observability and Grafana Dashboards

### 11.1 Grafana Setup

The `docker-compose.yml` includes a Grafana instance pre-configured to connect to the PostgreSQL database. Dashboard JSON and datasource config are auto-provisioned on startup.

```yaml
# docker-compose.yml (relevant services)
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: tacklebox
      POSTGRES_USER: tacklebox
      POSTGRES_PASSWORD: tacklebox
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards

volumes:
  pgdata:
```

### 11.2 Datasource Provisioning

```yaml
# grafana/provisioning/datasources/postgres.yml
apiVersion: 1
datasources:
  - name: Tacklebox PostgreSQL
    type: postgres
    url: db:5432
    database: tacklebox
    user: tacklebox
    secureJsonData:
      password: tacklebox
    jsonData:
      sslmode: disable
      maxOpenConns: 5
      postgresVersion: 1600
```

### 11.3 Dashboard Panels

The main dashboard (`grafana/dashboards/tacklebox.json`) includes these panels. Each panel uses a direct PostgreSQL query.

#### Panel 1: Active Sessions (Stat)

Shows the current number of active sessions.

```sql
SELECT count(*) as "Active Sessions"
FROM sessions
WHERE status = 'active';
```

#### Panel 2: Sessions Timeline (Time series)

Sessions started over time, grouped by source.

```sql
SELECT
  date_trunc('hour', started_at) as time,
  source,
  count(*) as sessions
FROM sessions
WHERE started_at > now() - interval '$__range'
GROUP BY time, source
ORDER BY time;
```

#### Panel 3: Tool Usage (Bar chart)

Tool invocation frequency over the selected time range.

```sql
SELECT
  tool_name,
  count(*) as invocations
FROM tool_events
WHERE created_at > now() - interval '$__range'
GROUP BY tool_name
ORDER BY invocations DESC;
```

#### Panel 4: Tool Failures (Time series)

Failed tool invocations over time.

```sql
SELECT
  date_trunc('hour', created_at) as time,
  tool_name,
  count(*) as failures
FROM tool_events
WHERE hook_event = 'PostToolUseFailure'
  AND created_at > now() - interval '$__range'
GROUP BY time, tool_name
ORDER BY time;
```

#### Panel 5: File Lock Warnings (Table)

Recent file conflict warnings.

```sql
SELECT
  te.created_at as time,
  s.cc_session_id as session,
  te.tool_input->>'file_path' as file,
  te.decision as action
FROM tool_events te
JOIN sessions s ON s.id = te.session_id
WHERE te.decision = 'warn'
  AND te.created_at > now() - interval '$__range'
ORDER BY te.created_at DESC
LIMIT 50;
```

#### Panel 6: Stop Hook Blocks (Table)

When and why the Stop hook prevented Claude from stopping.

```sql
SELECT
  sb.created_at as time,
  s.cc_session_id as session,
  sb.reason
FROM stop_blocks sb
JOIN sessions s ON s.id = sb.session_id
WHERE sb.created_at > now() - interval '$__range'
ORDER BY sb.created_at DESC
LIMIT 50;
```

#### Panel 7: Notification Types (Pie chart)

Distribution of notification types.

```sql
SELECT
  notification_type,
  count(*) as total
FROM notifications
WHERE created_at > now() - interval '$__range'
GROUP BY notification_type;
```

#### Panel 8: Subagent Activity (Bar chart)

Subagent spawns by type.

```sql
SELECT
  agent_type,
  count(*) as spawns
FROM subagent_events
WHERE hook_event = 'SubagentStart'
  AND created_at > now() - interval '$__range'
GROUP BY agent_type
ORDER BY spawns DESC;
```

### 11.4 Additional SQL Queries

These are useful for ad-hoc investigation outside Grafana:

#### Most edited files (last 24h)

```sql
SELECT
  tool_input->>'file_path' as file_path,
  count(*) as edits
FROM tool_events
WHERE tool_name IN ('Write', 'Edit')
  AND hook_event = 'PostToolUse'
  AND created_at > now() - interval '24 hours'
GROUP BY file_path
ORDER BY edits DESC
LIMIT 20;
```

#### Session duration distribution

```sql
SELECT
  cc_session_id,
  source,
  EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at)) / 60 as duration_minutes,
  status
FROM sessions
WHERE started_at > now() - interval '7 days'
ORDER BY started_at DESC;
```

---

## 12. Testing Strategy

Tests use pytest with httpx (via FastAPI's `TestClient`) and an isolated test database. No real Claude Code session is needed — tests POST JSON to hook endpoints and assert on responses and database state.

### 12.1 Test Database Setup

Tests use a separate PostgreSQL database (`tacklebox_test`) that is created and migrated before the test suite runs and dropped afterward.

```python
# tests/conftest.py
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from tacklebox.main import app
from tacklebox.db import get_db
from tacklebox.config import settings

TEST_DB_URL = settings.DATABASE_URL.replace("/tacklebox", "/tacklebox_test")
test_engine = create_async_engine(TEST_DB_URL)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create tables once for the entire test session."""
    from tacklebox.models import Base
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def db():
    """Per-test database session with rollback."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = TestSession(bind=conn)
        yield session
        await trans.rollback()


@pytest.fixture
async def client(db):
    """FastAPI test client wired to the test database."""
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

### 12.2 Test: Session Lifecycle

```python
# tests/test_session_lifecycle.py
import pytest


@pytest.mark.anyio
async def test_session_start_creates_session(client, db):
    """SessionStart creates a new session row and returns context."""
    response = await client.post("/hooks/session-start", json={
        "session_id": "test-session-1",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/home/user/project",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    assert response.status_code == 200
    # On a fresh DB, no context to inject
    body = response.json()
    # Should be {} or have empty additionalContext
    assert "decision" not in body  # SessionStart never blocks


@pytest.mark.anyio
async def test_session_start_upsert(client, db):
    """Repeated SessionStart with same session_id upserts, not duplicates."""
    payload = {
        "session_id": "test-session-upsert",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/home/user/project",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-sonnet-4-6",
    }
    await client.post("/hooks/session-start", json=payload)
    # Simulate compaction restart
    payload["source"] = "compact"
    response = await client.post("/hooks/session-start", json=payload)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_session_end_marks_completed(client, db):
    """SessionEnd marks the session as completed."""
    # Create session first
    await client.post("/hooks/session-start", json={
        "session_id": "test-session-end",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/home/user/project",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    # End it
    response = await client.post("/hooks/session-end", json={
        "session_id": "test-session-end",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/home/user/project",
        "permission_mode": "default",
        "hook_event_name": "SessionEnd",
        "reason": "other",
    })
    assert response.status_code == 200
```

### 12.3 Test: PreToolUse File Lock Warning

```python
# tests/test_file_lock.py
import pytest


@pytest.mark.anyio
async def test_file_lock_warns_on_conflict(client, db):
    """PreToolUse warns when another session recently edited the same file."""
    # Session A writes a file
    await client.post("/hooks/session-start", json={
        "session_id": "session-a", "transcript_path": "/tmp/a.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "SessionStart", "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    await client.post("/hooks/post-tool-use", json={
        "session_id": "session-a", "transcript_path": "/tmp/a.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "PostToolUse",
        "tool_name": "Write", "tool_use_id": "tu-1",
        "tool_input": {"file_path": "/project/src/api.py", "content": "..."},
        "tool_response": {"filePath": "/project/src/api.py", "success": True},
    })

    # Session B tries to edit the same file
    await client.post("/hooks/session-start", json={
        "session_id": "session-b", "transcript_path": "/tmp/b.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "SessionStart", "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    response = await client.post("/hooks/pre-tool-use", json={
        "session_id": "session-b", "transcript_path": "/tmp/b.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit", "tool_use_id": "tu-2",
        "tool_input": {"file_path": "/project/src/api.py",
                       "old_string": "x", "new_string": "y"},
    })
    assert response.status_code == 200
    body = response.json()
    # Should warn but allow
    specific = body.get("hookSpecificOutput", {})
    assert specific.get("permissionDecision") == "allow"
    assert "session-a" in specific.get("additionalContext", "")


@pytest.mark.anyio
async def test_no_warning_without_conflict(client, db):
    """PreToolUse returns no warning when no other session edited the file."""
    await client.post("/hooks/session-start", json={
        "session_id": "session-solo", "transcript_path": "/tmp/s.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "SessionStart", "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    response = await client.post("/hooks/pre-tool-use", json={
        "session_id": "session-solo", "transcript_path": "/tmp/s.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Write", "tool_use_id": "tu-3",
        "tool_input": {"file_path": "/project/src/new_file.py", "content": "..."},
    })
    assert response.status_code == 200
    body = response.json()
    # No warning — should be empty or no permissionDecision
    specific = body.get("hookSpecificOutput", {})
    assert specific.get("permissionDecision") is None or specific.get("permissionDecision") == "allow"
```

### 12.4 Test: Stop Hook Infinite Loop Prevention

```python
# tests/test_stop_handler.py
import pytest


@pytest.mark.anyio
async def test_stop_allows_when_no_tasks(client, db):
    """Stop allows when there are no incomplete tasks."""
    await client.post("/hooks/session-start", json={
        "session_id": "session-stop", "transcript_path": "/tmp/t.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "SessionStart", "source": "startup",
        "model": "claude-sonnet-4-6",
    })
    response = await client.post("/hooks/stop", json={
        "session_id": "session-stop", "transcript_path": "/tmp/t.jsonl",
        "cwd": "/project", "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": "Done.",
    })
    assert response.status_code == 200
    body = response.json()
    assert body.get("decision") is None  # no block


@pytest.mark.anyio
async def test_stop_safety_valve_after_max_blocks(client, db):
    """Stop allows after STOP_MAX_BLOCKS blocks to prevent infinite loops."""
    await client.post("/hooks/session-start", json={
        "session_id": "session-loop", "transcript_path": "/tmp/t.jsonl",
        "cwd": "/loop-project", "permission_mode": "default",
        "hook_event_name": "SessionStart", "source": "startup",
        "model": "claude-sonnet-4-6",
    })

    # Set up incomplete tasks so stop is blocked
    # (This would normally be set via the context API or PostToolUse handler)
    # ... seed session_context with incomplete_tasks ...

    # Simulate hitting the safety valve by sending stop_hook_active=True
    # after max blocks
    for i in range(4):  # STOP_MAX_BLOCKS default is 3
        response = await client.post("/hooks/stop", json={
            "session_id": "session-loop", "transcript_path": "/tmp/t.jsonl",
            "cwd": "/loop-project", "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": i > 0,  # True after first block
            "last_assistant_message": f"Attempt {i}",
        })

    # Last response should allow stop (safety valve)
    assert response.json().get("decision") is None
```

### 12.5 Running Tests

```bash
# Create test database
createdb tacklebox_test

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src/server --cov-report=term-missing

# Run a specific test file
pytest tests/test_file_lock.py -v
```

---

## 13. Security Considerations

- **Localhost binding:** By default, the server binds to 127.0.0.1. Do not expose it to 0.0.0.0 without adding authentication.
- **HTTP hook headers:** For remote deployments, use the `headers` and `allowedEnvVars` fields on HTTP hooks to pass authentication tokens without hardcoding secrets in settings files:
  ```json
  {
    "type": "http",
    "url": "https://hooks.example.com/hooks/pre-tool-use",
    "headers": { "Authorization": "Bearer $HOOKS_API_TOKEN" },
    "allowedEnvVars": ["HOOKS_API_TOKEN"]
  }
  ```
- **No secrets in hook input:** Claude Code hook input includes tool parameters, which may contain file contents. Ensure the database is not accessible to untrusted users.
- **2xx requirement for blocking:** Non-2xx HTTP responses are always treated as non-blocking errors. A misconfigured server that returns 500 will never accidentally block Claude — but it also means a down server can't enforce file locks. Monitor server health.
- **Database credentials:** Use environment variables or a `.env` file (not committed) for the DATABASE_URL. Never put credentials in the Claude Code settings files.
- **Migration discipline:** Use Alembic for all schema changes. Never alter tables manually in production.
- **Stop hook safety:** Always check `stop_hook_active` and enforce a maximum block count via `STOP_MAX_BLOCKS` to prevent infinite loops where Claude can never stop.
- **Prompt privacy:** The UserPromptSubmit handler receives the user's full prompt text. By default, log only a character count, not the content. Enable full logging via an opt-in `LOG_PROMPTS=true` setting.

---

## 14. Setup Guide

### 14.1 Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Docker and Docker Compose (for Grafana; optional if running Grafana separately)

### 14.2 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/tacklebox.git
cd tacklebox

# 2. Start PostgreSQL and Grafana
docker compose up -d db grafana

# 3. Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Copy environment template and edit if needed
cp .env.example .env
# Default DATABASE_URL points to the Docker PostgreSQL

# 5. Run database migrations
alembic upgrade head

# 6. Start the server
uvicorn src.tacklebox.main:app --host 127.0.0.1 --port 8420 --reload

# 7. Verify it's running
curl http://localhost:8420/health
# → {"status": "ok"}
```

### 14.3 Configure Claude Code Hooks

Copy the settings block from section 7.1 into your Claude Code settings file. Choose the scope:

- **All projects:** `~/.claude/settings.json`
- **Single project:** `.claude/settings.json` in the project root

Then restart Claude Code (or start a new session) for hooks to take effect.

### 14.4 Verify End to End

1. Start a Claude Code session in a project.
2. Check the server logs — you should see a SessionStart event.
3. Ask Claude to write a file. You should see PreToolUse and PostToolUse events.
4. Open Grafana at `http://localhost:3000` (default login: admin/admin).
5. Navigate to the "Tacklebox" dashboard. You should see the session and tool events.

### 14.5 Running as a Background Service (macOS)

For persistent local use, create a launchd plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tacklebox</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/.venv/bin/uvicorn</string>
        <string>src.tacklebox.main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8420</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/tacklebox</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DATABASE_URL</key>
        <string>postgresql+asyncpg://tacklebox:tacklebox@localhost/tacklebox</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/tacklebox.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/tacklebox.stderr.log</string>
</dict>
</plist>
```

```bash
# Install and start
cp com.tacklebox.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tacklebox.plist

# Check status
launchctl list | grep tacklebox

# Stop
launchctl unload ~/Library/LaunchAgents/com.tacklebox.plist
```

---

## 15. Next Steps

With this architecture in place, the implementation path is:

1. **Scaffold the project:** Create the project with `pyproject.toml`, `docker-compose.yml`, `.env.example`, and the directory layout from section 10.1.
2. **Define models and schemas:** Implement `models.py` (SQLAlchemy) and `schemas.py` (Pydantic) from sections 4 and 5.
3. **Run the initial migration:** Write `001_initial.py` in Alembic creating all tables from section 5.
4. **Implement the fail-open wrapper and core endpoints:** Start with SessionStart and SessionEnd (sections 6.1, 6.2) to verify the data flow end to end.
5. **Add tool event endpoints:** PreToolUse, PostToolUse, PostToolUseFailure (sections 6.3–6.5) with audit logging.
6. **Implement coordination services:** File lock detection (section 8.1) and the Stop handler with `stop_hook_active` guard (sections 6.8, 8.2).
7. **Add remaining endpoints:** PermissionRequest, UserPromptSubmit, Notification, SubagentStart/Stop, PreCompact.
8. **Build context injection:** Implement the summary builder (section 8.3) and wire it into SessionStart.
9. **Write tests:** Cover session lifecycle, file lock detection, and stop loop prevention (section 12).
10. **Configure hooks:** Copy the settings block from section 7.1 and test with a live Claude Code session.
11. **Set up Grafana:** Run `docker compose up grafana`, import the dashboard, and verify panels populate.
12. **Publish:** Write a README, add the launchd plist example, and push to GitHub.
