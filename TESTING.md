# Testing Tacklebox

This guide walks through setting up, running, and validating Tacklebox from scratch.

---

## Prerequisites

- **Python 3.11+** (3.13 recommended)
- **Docker Desktop** (for PostgreSQL and Grafana)
- **Claude Code** (for live hook testing)

---

## 1. Start the Infrastructure

Open Docker Desktop, then start PostgreSQL and Grafana:

```bash
docker compose up -d
```

Verify both containers are running:

```bash
docker compose ps
```

You should see `tacklebox-db-1` (postgres:16) and `tacklebox-grafana-1` (grafana) both with status `Up`.

> **Already have PostgreSQL locally?** If port 5432 is taken by a local install, either stop the local Postgres first or change the port mapping in `docker-compose.yml` (e.g., `"5433:5432"`) and update `DATABASE_URL` accordingly.

---

## 2. Install the Python Package

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Verify the install:

```bash
python -c "from tacklebox.config import settings; print(settings.PORT)"
# Should print: 8420
```

---

## 3. Configure Environment

Copy the example env file:

```bash
cp .env.example .env
```

The defaults work with the Docker Compose setup. If you changed the Postgres port or credentials, edit `.env` to match:

```
DATABASE_URL=postgresql+asyncpg://tacklebox:tacklebox@localhost/tacklebox
```

---

## 4. Run Database Migrations

```bash
alembic upgrade head
```

Expected output:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema - all 6 tables
```

This creates 6 tables: `sessions`, `tool_events`, `session_context`, `notifications`, `subagent_events`, `stop_blocks`.

You can verify with:

```bash
docker compose exec db psql -U tacklebox -d tacklebox -c "\dt"
```

---

## 5. Start the Server

```bash
uvicorn tacklebox.main:app --host 127.0.0.1 --port 8420 --reload
```

You should see:

```
INFO [tacklebox] Database connection verified
INFO: Uvicorn running on http://127.0.0.1:8420
```

Test the health endpoint:

```bash
curl http://localhost:8420/health
# {"status":"ok"}
```

---

## 6. Run the Automated Test Suite

The tests require a separate `tacklebox_test` database. Create it first:

```bash
docker compose exec db psql -U tacklebox -d postgres -c "CREATE DATABASE tacklebox_test OWNER tacklebox;"
```

Then run all 15 tests:

```bash
pytest tests/ -v
```

Expected output:

```
tests/test_context_injection.py::test_startup_no_context_on_fresh_db PASSED
tests/test_context_injection.py::test_project_context_injected_on_start PASSED
tests/test_context_injection.py::test_coordination_count_in_context PASSED
tests/test_file_lock.py::test_file_lock_warns_on_conflict PASSED
tests/test_file_lock.py::test_no_warning_without_conflict PASSED
tests/test_pre_tool_use.py::test_pre_tool_use_logs_event PASSED
tests/test_pre_tool_use.py::test_post_tool_use_updates_context PASSED
tests/test_pre_tool_use.py::test_post_tool_use_failure_logs PASSED
tests/test_session_lifecycle.py::test_session_start_creates_session PASSED
tests/test_session_lifecycle.py::test_session_start_upsert PASSED
tests/test_session_lifecycle.py::test_session_end_marks_completed PASSED
tests/test_session_lifecycle.py::test_session_auto_creates_on_missing PASSED
tests/test_stop_handler.py::test_stop_allows_when_no_tasks PASSED
tests/test_stop_handler.py::test_stop_blocks_with_incomplete_tasks PASSED
tests/test_stop_handler.py::test_stop_safety_valve_after_max_blocks PASSED

15 passed
```

### What the tests cover

| Test file | What it validates |
|-----------|-------------------|
| `test_session_lifecycle.py` | Session create, upsert on re-start, end marks completed, auto-create on unknown session |
| `test_context_injection.py` | No context on fresh DB, project context injected on SessionStart, coordination count shows other active sessions |
| `test_pre_tool_use.py` | Tool event logging, post-tool-use context updates, failure logging |
| `test_file_lock.py` | Warns when another session recently edited the same file, no warning without conflict |
| `test_stop_handler.py` | Allows stop with no tasks, blocks with incomplete tasks, safety valve after max blocks |

---

## 7. Manual Smoke Test with curl

With the server running, simulate a full hook lifecycle:

### Session Start

```bash
curl -s -X POST http://localhost:8420/hooks/session-start \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual-test-1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/myproject",
    "permission_mode": "default",
    "hook_event_name": "SessionStart",
    "source": "startup",
    "model": "claude-sonnet-4-6"
  }' | python3 -m json.tool
```

### Pre Tool Use (Write)

```bash
curl -s -X POST http://localhost:8420/hooks/pre-tool-use \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual-test-1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/myproject",
    "permission_mode": "default",
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_use_id": "tu-001",
    "tool_input": {"file_path": "/home/user/myproject/src/app.py", "content": "print(1)"}
  }' | python3 -m json.tool
```

### Post Tool Use (Write)

```bash
curl -s -X POST http://localhost:8420/hooks/post-tool-use \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual-test-1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/myproject",
    "permission_mode": "default",
    "hook_event_name": "PostToolUse",
    "tool_name": "Write",
    "tool_use_id": "tu-001",
    "tool_input": {"file_path": "/home/user/myproject/src/app.py", "content": "print(1)"},
    "tool_response": {"filePath": "/home/user/myproject/src/app.py", "success": true}
  }' | python3 -m json.tool
```

### Stop (should allow — no incomplete tasks)

```bash
curl -s -X POST http://localhost:8420/hooks/stop \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual-test-1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/myproject",
    "permission_mode": "default",
    "hook_event_name": "Stop",
    "stop_hook_active": false,
    "last_assistant_message": "All done."
  }' | python3 -m json.tool
```

### Session End

```bash
curl -s -X POST http://localhost:8420/hooks/session-end \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual-test-1",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/myproject",
    "permission_mode": "default",
    "hook_event_name": "SessionEnd",
    "reason": "other"
  }' | python3 -m json.tool
```

### Verify the data was recorded

```bash
curl -s "http://localhost:8420/sessions?status=completed" | python3 -m json.tool
```

---

## 8. Test File Lock Detection

This validates that Tacklebox warns when two sessions edit the same file.

```bash
# Session A starts and writes a file
curl -s -X POST http://localhost:8420/hooks/session-start \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-a","transcript_path":"/tmp/a.jsonl","cwd":"/project","permission_mode":"default","hook_event_name":"SessionStart","source":"startup","model":"claude-sonnet-4-6"}'

curl -s -X POST http://localhost:8420/hooks/post-tool-use \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-a","transcript_path":"/tmp/a.jsonl","cwd":"/project","permission_mode":"default","hook_event_name":"PostToolUse","tool_name":"Write","tool_use_id":"tu-1","tool_input":{"file_path":"/project/src/shared.py","content":"..."},"tool_response":{"success":true}}'

# Session B starts and tries to edit the SAME file
curl -s -X POST http://localhost:8420/hooks/session-start \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-b","transcript_path":"/tmp/b.jsonl","cwd":"/project","permission_mode":"default","hook_event_name":"SessionStart","source":"startup","model":"claude-sonnet-4-6"}'

curl -s -X POST http://localhost:8420/hooks/pre-tool-use \
  -H "Content-Type: application/json" \
  -d '{"session_id":"session-b","transcript_path":"/tmp/b.jsonl","cwd":"/project","permission_mode":"default","hook_event_name":"PreToolUse","tool_name":"Edit","tool_use_id":"tu-2","tool_input":{"file_path":"/project/src/shared.py","old_string":"x","new_string":"y"}}' | python3 -m json.tool
```

Expected response (Session B gets a warning):

```json
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": "Warning: /project/src/shared.py was edited 0 minutes ago by session session-a which is still active. Proceed with caution \u2014 your changes may conflict."
    }
}
```

---

## 9. Test Stop Hook Blocking

This validates that the stop hook blocks when there are incomplete tasks, and that the safety valve prevents infinite loops.

```bash
# Start a session
curl -s -X POST http://localhost:8420/hooks/session-start \
  -H "Content-Type: application/json" \
  -d '{"session_id":"stop-test","transcript_path":"/tmp/t.jsonl","cwd":"/stop-project","permission_mode":"default","hook_event_name":"SessionStart","source":"startup","model":"claude-sonnet-4-6"}'

# Set incomplete tasks
curl -s -X PUT http://localhost:8420/context \
  -H "Content-Type: application/json" \
  -d '{"cwd":"/stop-project","session_id":"stop-test","key":"incomplete_tasks","value":["Write unit tests","Fix auth bug"]}'

# Try to stop — should be blocked
curl -s -X POST http://localhost:8420/hooks/stop \
  -H "Content-Type: application/json" \
  -d '{"session_id":"stop-test","transcript_path":"/tmp/t.jsonl","cwd":"/stop-project","permission_mode":"default","hook_event_name":"Stop","stop_hook_active":false,"last_assistant_message":"Done."}' | python3 -m json.tool
```

Expected response:

```json
{
    "decision": "block",
    "reason": "Tasks still incomplete: Write unit tests, Fix auth bug"
}
```

---

## 10. Test with a Live Claude Code Session

This is the real end-to-end test. The hooks config is already in `.claude/settings.json`.

1. Make sure the server is running:

   ```bash
   source .venv/bin/activate
   uvicorn tacklebox.main:app --host 127.0.0.1 --port 8420 --reload
   ```

2. Open a **new Claude Code session** in the tacklebox project directory. You should see `SessionStart` logged in the server terminal.

3. Ask Claude to do something that triggers hooks:
   - Write or edit a file (triggers `PreToolUse` and `PostToolUse`)
   - Run a bash command (triggers `PreToolUse`, `PostToolUse` or `PostToolUseFailure`)

4. Watch the server logs. You should see requests like:

   ```
   INFO: 127.0.0.1:xxxxx - "POST /hooks/session-start HTTP/1.1" 200 OK
   INFO: 127.0.0.1:xxxxx - "POST /hooks/pre-tool-use HTTP/1.1" 200 OK
   INFO: 127.0.0.1:xxxxx - "POST /hooks/post-tool-use HTTP/1.1" 200 OK
   ```

5. Query the sessions API to see your live session:

   ```bash
   curl -s "http://localhost:8420/sessions?status=active" | python -m json.tool
   ```

> **To apply hooks globally** (all Claude Code projects, not just tacklebox), copy `.claude/settings.json` to `~/.claude/settings.json`.

---

## 11. Check Grafana Dashboards

1. Open http://localhost:3000 in your browser.
2. Login with `admin` / `tacklebox` (skip the password change prompt).
3. Navigate to **Dashboards** in the left sidebar.
4. Open the **Tacklebox** dashboard.

You should see 8 panels:

| Panel | Type | What it shows |
|-------|------|---------------|
| Active Sessions | Stat | Current count of active sessions |
| Sessions Timeline | Time series | Sessions started over time by source |
| Tool Usage | Bar chart | Tool invocation counts |
| Tool Failures | Time series | Failed tool invocations over time |
| File Lock Warnings | Table | Recent file conflict warnings |
| Stop Blocks | Table | When/why the stop hook blocked |
| Notification Types | Pie chart | Distribution of notification types |
| Subagent Activity | Bar chart | Subagent spawns by type |

> **Note:** The Grafana datasource is configured to connect to `db:5432` (the Docker network hostname). If you're running PostgreSQL outside of Docker, you'll need to edit `grafana/provisioning/datasources/postgres.yml` and change `url: db:5432` to `url: host.docker.internal:5432`.

---

## 12. Verify the REST APIs

Beyond the hook endpoints, Tacklebox provides query APIs:

### List all sessions

```bash
curl -s "http://localhost:8420/sessions" | python -m json.tool
```

### Filter by status

```bash
curl -s "http://localhost:8420/sessions?status=active" | python -m json.tool
```

### Get events for a specific session

First get a session ID from the list above, then:

```bash
curl -s "http://localhost:8420/sessions/<uuid>/events" | python -m json.tool
```

### Read project context

```bash
curl -s "http://localhost:8420/context?cwd=/home/user/myproject" | python -m json.tool
```

### Write project context

```bash
curl -s -X PUT http://localhost:8420/context \
  -H "Content-Type: application/json" \
  -d '{"cwd":"/home/user/myproject","session_id":"manual-test-1","key":"sprint_goal","value":{"goal":"Ship auth feature"}}'
```

### Interactive API docs

FastAPI auto-generates OpenAPI docs at http://localhost:8420/docs. You can explore and test all endpoints interactively from the browser.

---

## Troubleshooting

### Server won't start — "Database unavailable at startup"

PostgreSQL isn't running or the connection string is wrong. Check:

```bash
docker compose ps         # Is the db container running?
docker compose logs db    # Any errors?
```

### Tests fail with "role does not exist"

The test database hasn't been created:

```bash
docker compose exec db psql -U tacklebox -d postgres -c "CREATE DATABASE tacklebox_test OWNER tacklebox;"
```

### Hooks not firing in Claude Code

- Verify the server is running: `curl http://localhost:8420/health`
- Verify hooks config exists: `cat .claude/settings.json`
- Start a **new** Claude Code session (hooks are loaded at session start)
- Check that the hook event matches a configured matcher (e.g., `PreToolUse` only fires for `Write|Edit|Bash`, not `Read` or `Glob`)

### Grafana shows no data

- Verify data exists: `curl -s "http://localhost:8420/sessions" | python -m json.tool`
- Check the datasource config points to the right Postgres host (see note in section 11)
- Make sure the time range in Grafana covers when events were created (use "Last 1 hour" or "Last 24 hours")

### Port 5432 already in use

You have a local PostgreSQL install. Either:
- Stop it: `brew services stop postgresql` (or your equivalent)
- Or change the Docker port in `docker-compose.yml` to `"5433:5432"` and update `DATABASE_URL` in `.env`

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start PostgreSQL + Grafana |
| `docker compose down` | Stop everything |
| `alembic upgrade head` | Run database migrations |
| `uvicorn tacklebox.main:app --port 8420 --reload` | Start the server |
| `pytest tests/ -v` | Run all 15 tests |
| `curl http://localhost:8420/health` | Check server health |
| `curl http://localhost:8420/docs` | Open interactive API docs |
| `http://localhost:3000` | Open Grafana (admin/admin) |
