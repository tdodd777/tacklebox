<p align="center">
  <img src="tacklebox.png" alt="Tacklebox" width="400">
</p>

# Tacklebox

*Where you keep your hooks.*

A FastAPI + PostgreSQL + Grafana server that captures [Claude Code hook](https://docs.anthropic.com/en/docs/claude-code/hooks) events, enabling session coordination, context persistence, and audit logging across Claude Code sessions.

## What It Does

- **Session tracking** — Records when Claude Code sessions start, end, and what they do
- **Context persistence** — Stores project-scoped and session-scoped key-value context that survives across sessions
- **File lock detection** — Warns when two sessions are editing the same file
- **Stop hook blocking** — Prevents a session from ending if it has incomplete tasks (with a safety valve)
- **Context injection** — Automatically injects relevant context from prior sessions on startup
- **Coordination** — Shows how many other active sessions are working in the same project
- **Observability** — Grafana dashboard with 8 panels for monitoring sessions, tool usage, file conflicts, and more

## Architecture

```
Claude Code ──HTTP hooks──▶ Tacklebox (FastAPI :8420) ──▶ PostgreSQL
                                          │
                                    Grafana (:3000) reads from DB
```

18 hook endpoints handle events across the Claude Code lifecycle:

| Category | Endpoints |
|----------|-----------|
| Session | `session-start`, `session-end` |
| Tools | `pre-tool-use`, `post-tool-use`, `post-tool-use-failure`, `permission-request` |
| Stop | `stop`, `subagent-start`, `subagent-stop` |
| Other | `notification`, `pre-compact`, `user-prompt`, `teammate-idle`, `task-completed` |

All handlers use a **fail-open** pattern — any unhandled exception returns an empty `{}` with status 200, so hooks never block Claude Code.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker Desktop (for PostgreSQL and Grafana)

### Setup

```bash
# Start PostgreSQL and Grafana
docker compose up -d

# Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment (defaults work with Docker Compose)
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the server
uvicorn tacklebox.main:app --host 127.0.0.1 --port 8420 --reload
```

Verify it's running:

```bash
curl http://localhost:8420/health
# {"status":"ok"}
```

### Enable Hooks

Copy `.claude/settings.json` to your global Claude Code settings (`~/.claude/settings.json`) or leave it in the repo for project-scoped hooks. The config registers 12 hook event types pointing at `http://localhost:8420/hooks/*`.

## Configuration

All settings are optional with sensible defaults. Set via `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://tacklebox:tacklebox@localhost/tacklebox` | PostgreSQL connection string |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8420` | Server port |
| `FILE_LOCK_STALENESS_SEC` | `300` | Seconds before a file edit is no longer considered "recent" |
| `CONTEXT_SUMMARY_LIMIT` | `20` | Max context entries injected on SessionStart |
| `STOP_MAX_BLOCKS` | `3` | Allow stop after this many blocks (safety valve) |
| `SESSION_TIMEOUT_SEC` | `14400` | Mark sessions interrupted after 4 hours of inactivity |
| `LOG_FILE` | `~/.local/share/tacklebox/server.log` | Log file path |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_PROMPTS` | `false` | Log full prompts (`true`) or just a hash (`false`) |

## Database

6 tables managed via Alembic migrations:

- **sessions** — Active/completed/interrupted Claude Code sessions
- **tool_events** — Every tool invocation with input/output (JSONB)
- **session_context** — Key-value context entries (project or session scoped)
- **notifications** — Idle notices, warnings, errors from Claude Code
- **subagent_events** — Subagent spawn and stop events
- **stop_blocks** — Records of when/why session termination was blocked

## API

Interactive docs available at `http://localhost:8420/docs` when the server is running.

### Query Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /sessions` | List sessions (filter by `status`, `cwd`) |
| `GET /sessions/{id}/events` | Get tool events for a session |
| `GET /context` | Query context entries (filter by `cwd`, `scope`) |
| `PUT /context` | Create or update context entries |

## Grafana Dashboard

Access at `http://localhost:3000` (admin/admin). The pre-provisioned dashboard includes:

- Active session count
- Sessions timeline (by source)
- Tool usage breakdown
- Tool failure tracking
- File lock warnings
- Stop block history
- Notification type distribution
- Subagent activity

## Testing

```bash
# Create test database
docker compose exec db psql -U tacklebox -d postgres \
  -c "CREATE DATABASE tacklebox_test OWNER tacklebox;"

# Run all 15 tests
pytest tests/ -v
```

Tests cover session lifecycle, context injection, file lock detection, pre-tool-use handling, and stop hook blocking. See [TESTING.md](TESTING.md) for the full setup and manual testing guide.

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

## Tech Stack

- **FastAPI** + **Uvicorn** — Async HTTP server
- **SQLAlchemy** (async) + **asyncpg** — Database ORM and driver
- **Alembic** — Database migrations
- **PostgreSQL 16** — Primary data store
- **Grafana** — Dashboards and monitoring
- **pytest-asyncio** + **httpx** — Test framework
