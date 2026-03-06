<p align="center">
  <img src="tacklebox.png" alt="Tacklebox" width="400">
</p>

# Tacklebox

*Where you keep your hooks.*

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
Claude Code ──HTTP hooks──▶ Tacklebox (FastAPI :8420) ──▶ PostgreSQL
                                        │
                                  Grafana (:3000) reads from DB
```

14 hook endpoints across the Claude Code lifecycle. All handlers use a **fail-open** pattern — unhandled exceptions return `{}` with status 200, so hooks never block Claude Code. The `/health` endpoint exposes an error counter.

## Context Injection

On each new session, Tacklebox injects project context so Claude starts with awareness of prior work:

```
[context] sprint_goal: Ship dashboard filtering and session replay
[context] last_edited_files: ['src/auth.py', 'tests/test_auth.py']
[context] incomplete_tasks: [{'task': 'Add rate limiting', 'priority': 'high'}]
[coordination] 2 other active session(s) in this project:
  [session abc12] Edit src/api.py (30s ago)
  [session def45] Bash "pytest tests/" (2m ago)
[tasks] Recently completed:
  "Implement auth" (by alpha, 5m ago)
```

Coordination refreshes every 5 minutes via `UserPromptSubmit`. Solo sessions see nothing — no noise when you're working alone.

### Known Issue: `SessionStart` for New Sessions

Claude Code may discard `SessionStart` hook responses for new sessions ([anthropics/claude-code#10373](https://github.com/anthropics/claude-code/issues/10373)). Tacklebox works around this by also injecting context via `UserPromptSubmit` on the first prompt. If `SessionStart` worked, the context appears twice (harmless). If it was discarded, `UserPromptSubmit` catches it.

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

Add the hook configuration to your Claude Code settings (`~/.claude/settings.json`). See `.claude/settings.json` in this repo for the full config — it registers 14 hook event types pointing at `http://localhost:8420/hooks/*`.

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

22 tests covering session lifecycle, context injection, coordination, file lock detection, tool hooks, and stop blocking.

## Security

Designed for **localhost use**. For network deployment:

1. Set `API_KEY` to a strong random value
2. Change database credentials from defaults
3. Set `GRAFANA_ADMIN_PASSWORD` environment variable
4. Use TLS via a reverse proxy

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
