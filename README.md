<p align="center">
  <img src="tacklebox.png" alt="Tacklebox" width="400">
</p>

# Tacklebox

*Where you keep your hooks.*

## TL;DR

Tacklebox is a local server that makes Claude Code sessions smarter by remembering what happened before. When you start a new Claude session, it automatically gets context from previous sessions — what files were edited, what tasks are in progress, what errors occurred. If you're running multiple sessions in the same project, each one knows what the others are doing so they don't step on each other. All hook events are logged to PostgreSQL with a Grafana dashboard for visibility.

**In short:** plug it in, and every Claude Code session starts with full project awareness instead of a blank slate.

---

A FastAPI + PostgreSQL server that captures [Claude Code hook](https://docs.anthropic.com/en/docs/claude-code/hooks) events, providing context persistence, multi-session coordination, and audit logging.

## What It Does

- **Context injection** — New sessions automatically receive project context from prior sessions (edited files, sprint goals, incomplete tasks)
- **Multi-session coordination** — Each session sees what other sessions are actively doing (which files, which commands, how recently)
- **Session tracking** — Records session lifecycle, tool usage, and outcomes in PostgreSQL
- **File lock detection** — Warns when two sessions edit the same file
- **Stop hook blocking** — Prevents sessions from ending with incomplete tasks (with a safety valve after 3 blocks)
- **Grafana dashboard** — Pre-provisioned panels for monitoring sessions, tool usage, and file conflicts

## Architecture

```
Claude Code ──hooks──▶ Tacklebox (FastAPI :8420) ──▶ PostgreSQL
                                        │
                                  Grafana (:3000) reads from DB
```

16 hook endpoints across the Claude Code lifecycle. 8 use native `type: "http"` hooks; the remaining 8 use `type: "command"` with `curl`, because Claude Code only supports HTTP hooks for certain event types. All handlers use a **fail-open** pattern — unhandled exceptions return `{}` with status 200, so hooks never block Claude Code. The `/health` endpoint exposes an error counter.

## Context Injection

On each new session, Tacklebox injects project context so Claude starts with awareness of prior work:

```
[context] sprint_goal: Ship dashboard filtering and session replay
[context] last_edited_files: ['src/auth.py', 'tests/test_auth.py']
[context] incomplete_tasks: [{'task': 'Add rate limiting', 'priority': 'high'}]
[tool stats 24h] Bash: 38, Edit: 22, Write: 12, Read: 8
[recent errors]
  Bash: "npm test: ENOENT no such file..." (2h ago)
[recently edited] routes/sessions.py, services/context.py, config.py (+4 more)
[coordination] 2 other active session(s) in this project:
  [session abc12] "implement rate limiting" | Edit src/api.py (30s ago)
    files: api.py, models.py
  [session def45] Bash "pytest tests/" (2m ago)
  [overlap] session abc12 is also editing src/
[tasks] Recently completed:
  "Implement auth" (by alpha, 5m ago)
```

Coordination refreshes every 5 minutes via `UserPromptSubmit`. Solo sessions see nothing — no noise when you're working alone.

### Known Issue: `SessionStart` for New Sessions

`SessionStart` uses a `command`+`curl` hook (Claude Code doesn't support HTTP hooks for this event). However, Claude Code may still discard the response for new sessions ([anthropics/claude-code#10373](https://github.com/anthropics/claude-code/issues/10373)). Tacklebox works around this by also injecting context via `UserPromptSubmit` on the first prompt. If `SessionStart` worked, the context appears twice (harmless). If it was discarded, `UserPromptSubmit` catches it.

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
- Docker (optional, for Grafana)

### Setup

```bash
# Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment (defaults work with local PostgreSQL)
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the server
uvicorn tacklebox.main:app --host 127.0.0.1 --port 8420 --reload
```

Verify:

```bash
curl http://localhost:8420/health
# {"status":"ok","fail_open_errors":0}
```

### Enable Hooks

Add the hook configuration to your Claude Code settings (`~/.claude/settings.json`). See `.claude/settings.json` in this repo for the full config.

Claude Code only supports `type: "http"` hooks for 8 of 16 event types (Stop, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, SubagentStop, TaskCompleted). The other 8 (SessionStart, SessionEnd, SubagentStart, Notification, PreCompact, TeammateIdle, InstructionsLoaded, ConfigChange) silently ignore HTTP configs. Tacklebox uses `type: "command"` with `curl` for these — the server receives identical POST requests either way.

## Configuration

All settings are optional with sensible defaults. Set via `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://tacklebox:tacklebox@localhost/tacklebox` | PostgreSQL connection string |
| `PORT` | `8420` | Server port |
| `FILE_LOCK_STALENESS_SEC` | `300` | Seconds before a file edit is considered stale |
| `STOP_MAX_BLOCKS` | `3` | Safety valve: allow stop after this many blocks |
| `SESSION_TIMEOUT_SEC` | `14400` | Mark sessions interrupted after 4 hours |
| `LOG_PROMPTS` | `false` | Log full prompts (`true`) or just a hash (`false`) |
| `LOG_SESSION_INTENT` | `true` | Extract and store intent from first prompt per session |
| `API_KEY` | *(empty)* | Set to require `X-API-Key` header on all endpoints except `/health` |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Max request body size (1 MB) |
| `COORDINATION_ACTIVE_WINDOW_SEC` | `1800` | Exclude sessions idle longer than 30 min from coordination |
| `COORDINATION_REFRESH_SEC` | `300` | Min seconds between coordination re-injections |

## Database

6 tables managed via Alembic migrations:

- **sessions** — Claude Code session lifecycle
- **tool_events** — Tool invocations with input/output (JSONB)
- **session_context** — Key-value context (project or session scoped)
- **notifications** — Warnings and errors from Claude Code
- **subagent_events** — Subagent spawn and stop events
- **stop_blocks** — When/why session termination was blocked

## API

Interactive docs at `http://localhost:8420/docs`.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check + error counter |
| `GET /sessions` | List sessions (filter by `status`, `cwd`) |
| `GET /sessions/{id}/events` | Tool events for a session |
| `GET /context` | Query context entries (filter by `cwd`, `scope`) |
| `PUT /context` | Create or update context entries |
| `GET /hooks/status` | Diagnostic: last-seen timestamp and 24h count per hook event |

## Grafana Dashboard

<p align="center">
  <img src="grafana.png" alt="Tacklebox Grafana Dashboard" width="800">
</p>

Access at `http://localhost:3000` (default login: `admin` / `tacklebox`). Panels: active sessions, session timeline, tool usage, tool failures, file lock warnings, stop blocks.

## Testing

```bash
# Create test database
createdb -U tacklebox tacklebox_test

# Run tests
pytest tests/ -v
```

31 tests covering session lifecycle, context injection, coordination, file lock detection, tool hooks, stop blocking, session intent, overlap detection, and observability hooks.

## Security

Designed for **localhost use**. For network deployment:

1. Set `API_KEY` to a strong random value
2. Change database credentials from defaults
3. Set `GRAFANA_ADMIN_PASSWORD` environment variable
4. Use TLS via a reverse proxy

## User Guide

This section covers everything you can do with Tacklebox — both via direct API calls and by telling Claude what to do in natural language.

### Setting Project Context

Context keys are project-scoped key-value pairs that persist across sessions. Every new Claude session in the same directory receives all project context keys automatically.

**Manual (curl):**

```bash
# Set a sprint goal
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "/path/to/project", "session_id": "any-session-id", "key": "sprint_goal", "value": "Ship auth and rate limiting by Friday"}'

# Set team conventions
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "/path/to/project", "session_id": "any-session-id", "key": "conventions", "value": {"testing": "Always use pytest, never unittest", "style": "Google docstrings"}}'

# Set architectural notes
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "/path/to/project", "session_id": "any-session-id", "key": "architecture_notes", "value": "API layer is FastAPI, background jobs use Celery, auth is JWT-based"}'

# Read current context
curl -s "http://localhost:8420/context?cwd=/path/to/project" | python3 -m json.tool
```

The `session_id` field can be any string — it's used to associate the write with a session but doesn't need to be an active session. If the session doesn't exist, Tacklebox creates one automatically.

The `value` field accepts any JSON type: objects, arrays, strings, numbers. Values are stored as JSONB and rendered as-is in the injected context line `[context] key: value`.

**Pre-baked prompt (paste into Claude):**

```
Use curl to set project context on the Tacklebox server at localhost:8420.
Set the following project context keys for cwd "$(pwd)":

- sprint_goal: "Ship auth and rate limiting by Friday"
- conventions: {"testing": "Always use pytest", "style": "Google docstrings"}

Use PUT /context with Content-Type application/json. The session_id can be "manual".
```

### Managing Tasks (Stop Hook Blocking)

The `incomplete_tasks` context key controls whether Claude is allowed to end a session. When set to a non-empty list, the Stop hook returns `decision: "block"` and Claude must continue working. After 3 blocks (configurable via `STOP_MAX_BLOCKS`), the safety valve allows the session to end regardless.

**Manual (curl):**

```bash
# Block sessions from ending — Claude must finish these first
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "/path/to/project", "session_id": "any", "key": "incomplete_tasks", "value": [{"task": "Add rate limiting middleware", "priority": "high"}, {"task": "Write integration tests", "priority": "medium"}]}'

# Clear tasks — allow sessions to end normally
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "/path/to/project", "session_id": "any", "key": "incomplete_tasks", "value": []}'
```

**Pre-baked prompt:**

```
Use curl to set the "incomplete_tasks" context key on Tacklebox (localhost:8420, PUT /context).
cwd: "$(pwd)", session_id: "manual"
Set value to: [{"task": "Add rate limiting middleware", "priority": "high"}]
This will prevent Claude sessions from ending until the task is done.
```

### Viewing Active Sessions

**Manual (curl):**

```bash
# List all active sessions
curl -s "http://localhost:8420/sessions?status=active" | python3 -m json.tool

# List sessions in a specific project
curl -s "http://localhost:8420/sessions?cwd=/path/to/project&status=active" | python3 -m json.tool

# List all sessions (active, completed, interrupted) with pagination
curl -s "http://localhost:8420/sessions?limit=20&offset=0" | python3 -m json.tool
```

**Pre-baked prompt:**

```
Use curl to query Tacklebox at localhost:8420. Show me all active sessions:
GET /sessions?status=active
Then show the tool events for the most recent session using GET /sessions/{id}/events?limit=20
```

### Viewing Session Tool Events

Every tool invocation (Write, Edit, Bash) and hook event (UserPromptSubmit, PostToolUseFailure, etc.) is recorded with full input/output as JSONB.

**Manual (curl):**

```bash
# Get the session's internal UUID first
curl -s "http://localhost:8420/sessions?status=active" | python3 -m json.tool

# Then query its events (replace UUID)
curl -s "http://localhost:8420/sessions/SESSION_UUID_HERE/events?limit=50" | python3 -m json.tool
```

**Pre-baked prompt:**

```
Use curl to query Tacklebox at localhost:8420.
1. GET /sessions?status=active to find active sessions
2. For each session, GET /sessions/{id}/events?limit=10 to see recent tool usage
Summarize what each session has been doing.
```

### Checking Hook Health

The `/hooks/status` endpoint shows the last time each hook type fired and its 24-hour count. Useful for verifying hooks are wired correctly.

**Manual (curl):**

```bash
curl -s http://localhost:8420/hooks/status | python3 -m json.tool
```

The response includes a `never_seen` array — any hook types that have never fired. If you expect all 16 hooks to be active, anything in `never_seen` indicates a wiring issue.

**Manual (health check):**

```bash
curl -s http://localhost:8420/health
# {"status":"ok","fail_open_errors":0}
```

The `fail_open_errors` counter increments every time a hook handler throws an exception (caught by the fail-open decorator). A non-zero value means something went wrong silently — check the server log at `~/.local/share/tacklebox/server.log`.

### Seeing What Context Gets Injected

Tacklebox injects context via `additionalContext` in hook responses. Claude receives this as a `<system-reminder>` tag. You can inspect the raw injection in three ways:

**1. Ask Claude directly:**

```
Repeat back verbatim the full contents of any "UserPromptSubmit hook additional context" you received in a system-reminder. Do not summarize — show the raw text in a code block.
```

**2. Simulate a session start via curl:**

```bash
curl -s http://localhost:8420/hooks/session-start \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "test-inspect-'$(date +%s)'", "transcript_path": "/tmp/t.jsonl", "cwd": "'$(pwd)'", "permission_mode": "default", "hook_event_name": "SessionStart", "source": "startup", "model": "claude-sonnet-4-6"}' \
  | python3 -m json.tool
```

**3. Simulate a user prompt via curl:**

```bash
curl -s http://localhost:8420/hooks/user-prompt \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "REAL_SESSION_ID_HERE", "transcript_path": "/tmp/t.jsonl", "cwd": "'$(pwd)'", "permission_mode": "default", "hook_event_name": "UserPromptSubmit", "prompt": "test"}' \
  | python3 -m json.tool
```

### Understanding the Injected Context Blocks

Here's what each block means and where its data comes from:

```
[context] sprint_goal: Ship auth by Friday        ← PUT /context (manual or via prompt)
[context] last_edited_files: ['src/api.py', ...]   ← Auto-populated by PostToolUse for Write/Edit
[context] incomplete_tasks: [...]                  ← PUT /context (controls Stop blocking)
[context] completed_tasks: [...]                   ← Auto-populated by TaskCompleted hook
```

```
[tool stats 24h] Bash: 38, Edit: 22, Write: 12    ← Aggregated from tool_events (all sessions, same cwd)
```

```
[recent errors]                                    ← From PostToolUseFailure events (last 3, 24h)
  Bash: "npm test: ENOENT..." (2h ago)
  Edit: "Permission denied..." (4h ago)
```

```
[recently edited] routes.py, models.py, ...        ← Distinct file paths from PostToolUse Write/Edit (24h)
```

```
[coordination] 2 other active session(s):          ← From sessions + tool_events tables
  [session abc12] "implement auth" | Edit api.py (30s ago)
    files: api.py, models.py                       ← Recent Write/Edit file paths for that session
  [session def45] Bash "pytest tests/" (2m ago)
  [overlap] session abc12 is also editing src/     ← Directory overlap between current + sibling sessions
```

```
[tasks] Recently completed:                        ← From TaskCompleted hook events (last hour)
  "Implement auth" (by alpha, 5m ago)
```

**What's automatic vs. manual:**

| Block | Source | Manual Setup Needed? |
|-------|--------|---------------------|
| `[context] sprint_goal` | `PUT /context` | Yes — you set it |
| `[context] last_edited_files` | PostToolUse hook | No — auto-tracked |
| `[context] incomplete_tasks` | `PUT /context` | Yes — you set it |
| `[context] completed_tasks` | TaskCompleted hook | No — auto-tracked |
| `[tool stats 24h]` | tool_events table | No — auto-aggregated |
| `[recent errors]` | PostToolUseFailure hook | No — auto-tracked |
| `[recently edited]` | PostToolUse hook | No — auto-aggregated |
| `[coordination]` | sessions + tool_events | No — auto-generated |
| `[overlap]` | tool_events directory analysis | No — auto-detected |
| `[tasks]` | TaskCompleted hook events | No — auto-tracked |
| Session intent | UserPromptSubmit (1st prompt) | No — auto-extracted |

### Multi-Session Workflows

Tacklebox's coordination features shine when running multiple Claude sessions in the same project. Here are common patterns:

**Parallel feature development:**

Open two terminals in the same repo. Each session sees what the other is doing — which files are being edited, what commands are running, and where there's directory overlap.

**Task assignment with stop blocking:**

```bash
# Set tasks before starting sessions
curl -X PUT http://localhost:8420/context \
  -H 'Content-Type: application/json' \
  -d '{"cwd": "'$(pwd)'", "session_id": "manual", "key": "incomplete_tasks", "value": [{"task": "Add input validation to all endpoints"}, {"task": "Write tests for the auth module"}]}'
```

Now start two Claude sessions. Neither can exit until `incomplete_tasks` is cleared. After 3 attempts to exit, the safety valve kicks in.

**Checking what sessions are doing:**

```bash
# Quick overview: hook event counts
curl -s http://localhost:8420/hooks/status | python3 -m json.tool

# Detailed: active sessions and their recent tools
curl -s "http://localhost:8420/sessions?status=active" | python3 -m json.tool
```

### Querying the Database Directly

For deeper analysis, query PostgreSQL directly:

```bash
# Session intents (what each session is working on)
psql -U tacklebox -d tacklebox -c "
  SELECT s.cc_session_id, sc.value->>'intent' as intent, sc.created_at
  FROM session_context sc JOIN sessions s ON sc.session_id = s.id
  WHERE sc.key = 'session_intent'
  ORDER BY sc.created_at DESC LIMIT 10;"

# Tool usage breakdown by session
psql -U tacklebox -d tacklebox -c "
  SELECT s.cc_session_id, te.tool_name, count(*) as cnt
  FROM tool_events te JOIN sessions s ON te.session_id = s.id
  WHERE te.hook_event IN ('PostToolUse', 'PreToolUse')
    AND te.created_at > now() - interval '24 hours'
  GROUP BY s.cc_session_id, te.tool_name
  ORDER BY s.cc_session_id, cnt DESC;"

# Recent errors across all sessions
psql -U tacklebox -d tacklebox -c "
  SELECT s.cc_session_id, te.tool_name, te.error, te.created_at
  FROM tool_events te JOIN sessions s ON te.session_id = s.id
  WHERE te.hook_event = 'PostToolUseFailure'
  ORDER BY te.created_at DESC LIMIT 10;"

# Files edited in the last hour (with which session edited them)
psql -U tacklebox -d tacklebox -c "
  SELECT s.cc_session_id, te.tool_name, te.tool_input->>'file_path' as file_path, te.created_at
  FROM tool_events te JOIN sessions s ON te.session_id = s.id
  WHERE te.tool_name IN ('Write', 'Edit') AND te.hook_event = 'PostToolUse'
    AND te.created_at > now() - interval '1 hour'
  ORDER BY te.created_at DESC;"

# All project context keys for a directory
psql -U tacklebox -d tacklebox -c "
  SELECT key, value, updated_at FROM session_context
  WHERE cwd = '$(pwd)' AND scope = 'project'
  ORDER BY updated_at DESC;"

# Stop block history (why sessions were prevented from ending)
psql -U tacklebox -d tacklebox -c "
  SELECT sb.reason, sb.created_at, s.cc_session_id
  FROM stop_blocks sb JOIN sessions s ON sb.session_id = s.id
  ORDER BY sb.created_at DESC LIMIT 10;"
```

### Configuration Tuning

All settings can be changed in `.env` without restarting (the server reads them at startup):

```bash
# More aggressive file lock detection (warn if same file edited within 10 min)
FILE_LOCK_STALENESS_SEC=600

# Allow more stop blocks before safety valve (useful for long task lists)
STOP_MAX_BLOCKS=5

# Refresh coordination more frequently (every 2 min instead of 5)
COORDINATION_REFRESH_SEC=120

# Wider coordination window (include sessions idle up to 1 hour)
COORDINATION_ACTIVE_WINDOW_SEC=3600

# Enable full prompt logging (privacy tradeoff — useful for debugging)
LOG_PROMPTS=true

# Disable session intent extraction
LOG_SESSION_INTENT=false

# Require API key for all non-health endpoints
API_KEY=your-secret-key-here

# Increase request body limit to 5 MB (for large tool_response payloads)
MAX_REQUEST_BODY_BYTES=5242880
```

### Resetting State

```bash
# Clear all project context for a directory
psql -U tacklebox -d tacklebox -c "DELETE FROM session_context WHERE cwd = '/path/to/project' AND scope = 'project';"

# Mark all active sessions as completed (clean slate)
psql -U tacklebox -d tacklebox -c "UPDATE sessions SET status = 'completed', ended_at = now() WHERE status = 'active';"

# Nuclear option — truncate everything
psql -U tacklebox -d tacklebox -c "TRUNCATE stop_blocks, subagent_events, notifications, session_context, tool_events, sessions CASCADE;"
```

### Pre-Baked Prompts for Common Tasks

These prompts can be pasted into a Claude session to have it interact with Tacklebox on your behalf.

**Set up a new project with Tacklebox context:**

```
Use curl to configure Tacklebox project context at localhost:8420 (PUT /context, Content-Type: application/json).
Set these keys for cwd "$(pwd)" with session_id "manual":

1. sprint_goal — describe what we're working on this sprint
2. conventions — our coding conventions (testing framework, style, etc.)
3. architecture_notes — high-level architecture description

Ask me for the values before setting them.
```

**Review what Tacklebox knows about this project:**

```
Use curl to query Tacklebox at localhost:8420. Run these in order:
1. GET /context?cwd=$(pwd) — show all project context keys
2. GET /sessions?cwd=$(pwd)&status=active — show active sessions
3. GET /hooks/status — show hook health
4. GET /health — show error count
Summarize the results.
```

**Debug why context injection isn't working:**

```
Help me debug Tacklebox context injection. Run these curl commands against localhost:8420:

1. GET /health — check if the server is up and if fail_open_errors is non-zero
2. GET /hooks/status — check which hooks have fired and which are in never_seen
3. Simulate a session start:
   POST /hooks/session-start with body: {"session_id": "debug-test", "transcript_path": "/tmp/t.jsonl", "cwd": "$(pwd)", "permission_mode": "default", "hook_event_name": "SessionStart", "source": "startup", "model": "claude-sonnet-4-6"}
4. Simulate a user prompt:
   POST /hooks/user-prompt with body: {"session_id": "debug-test", "transcript_path": "/tmp/t.jsonl", "cwd": "$(pwd)", "permission_mode": "default", "hook_event_name": "UserPromptSubmit", "prompt": "test"}

Show me the raw responses. If additionalContext is empty, check the database:
   GET /context?cwd=$(pwd) to see if any project context exists.
```

**Monitor multi-session activity:**

```
Use curl to monitor Tacklebox at localhost:8420. Run these and summarize:
1. GET /sessions?status=active — list active sessions
2. For each active session, GET /sessions/{id}/events?limit=5 — show recent activity
3. GET /context?cwd=$(pwd) — show current project context
Tell me what each session is working on, what files they've touched, and if there are any incomplete tasks blocking session exits.
```

## Project Structure

```
src/tacklebox/
├── main.py              # FastAPI app, lifespan, stale session cleanup
├── config.py            # Settings via pydantic-settings
├── db.py                # Async SQLAlchemy engine + session factory
├── models.py            # 6 ORM models
├── schemas.py           # Pydantic request/response models
├── utils.py             # fail_open decorator
├── routes/
│   ├── sessions.py      # GET /sessions endpoints
│   ├── context.py       # GET/PUT /context endpoints
│   ├── hooks_session.py # SessionStart, SessionEnd, Notification, etc.
│   ├── hooks_tools.py   # PreToolUse, PostToolUse, PostToolUseFailure
│   └── hooks_stop.py    # Stop, SubagentStart, SubagentStop
└── services/
    ├── audit.py         # Session resolution + event logging
    ├── context.py       # Context summary builder + upsert
    ├── coordination.py  # File lock detection
    └── responses.py     # Response serialization
```
