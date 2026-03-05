async def test_startup_no_context_on_fresh_db(client):
    """SessionStart on a fresh DB returns empty (no context to inject)."""
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ctx-test-fresh",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/fresh-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    # No context available for a fresh project
    specific = body.get("hookSpecificOutput", {})
    # Either empty response or no additionalContext
    assert specific.get("additionalContext") is None or body == {}


async def test_project_context_injected_on_start(client):
    """SessionStart includes project context when available."""
    # Set up a session and add project context
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ctx-test-setter",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ctx-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    # Set context via API
    await client.put(
        "/context",
        json={
            "cwd": "/ctx-project",
            "session_id": "ctx-test-setter",
            "key": "sprint_goal",
            "value": {"goal": "Implement auth"},
        },
    )

    # New session should get context
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ctx-test-reader",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ctx-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    specific = body.get("hookSpecificOutput", {})
    ctx = specific.get("additionalContext", "")
    assert "sprint_goal" in ctx


async def test_coordination_count_in_context(client):
    """SessionStart shows other active sessions with their recent activity."""
    # Create session 1
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "coord-session-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/coord-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    # Session 1 performs a tool action so it shows in coordination
    await client.post(
        "/hooks/post-tool-use",
        json={
            "session_id": "coord-session-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/coord-project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/coord-project/src/api.py"},
            "tool_response": {"success": True},
            "tool_use_id": "tu-1",
        },
    )
    # Create session 2 — should see session 1's activity
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "coord-session-2",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/coord-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    specific = body.get("hookSpecificOutput", {})
    ctx = specific.get("additionalContext", "")
    assert "coordination" in ctx
    assert "1 other active session" in ctx
    assert "Edit" in ctx
    assert "api.py" in ctx


async def test_user_prompt_injects_context_on_first_prompt(client):
    """First UserPromptSubmit on a startup session returns additionalContext."""
    # Create a session and add project context
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ups-inject-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    await client.put(
        "/context",
        json={
            "cwd": "/ups-project",
            "session_id": "ups-inject-1",
            "key": "team_notes",
            "value": {"note": "Focus on performance"},
        },
    )

    # First prompt should inject context
    response = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "ups-inject-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Hello",
        },
    )
    assert response.status_code == 200
    body = response.json()
    specific = body.get("hookSpecificOutput", {})
    assert "team_notes" in specific.get("additionalContext", "")


async def test_user_prompt_skips_context_on_subsequent_prompts(client):
    """Second UserPromptSubmit returns empty (context already injected)."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ups-skip-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-skip-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )

    # First prompt sets the flag
    await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "ups-skip-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-skip-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "First prompt",
        },
    )

    # Second prompt should return empty
    response = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "ups-skip-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-skip-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Second prompt",
        },
    )
    assert response.status_code == 200
    assert response.json() == {}


async def test_resume_session_start_prevents_user_prompt_injection(client):
    """Resume SessionStart sets context_injected flag, so UserPromptSubmit skips."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "ups-resume-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-resume-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "resume",
            "model": "claude-sonnet-4-6",
        },
    )

    # UserPromptSubmit should skip injection (flag was set by SessionStart)
    response = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "ups-resume-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/ups-resume-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Hello after resume",
        },
    )
    assert response.status_code == 200
    assert response.json() == {}


async def test_coordination_shows_session_details(client):
    """Two sessions in the same cwd: session B sees session A's per-session activity."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "detail-a",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/detail-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    await client.post(
        "/hooks/post-tool-use",
        json={
            "session_id": "detail-a",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/detail-project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/ -v"},
            "tool_response": {"exitCode": "0"},
            "tool_use_id": "tu-detail-1",
        },
    )

    # Session B starts — should see session A's Bash command
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "detail-b",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/detail-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    ctx = response.json().get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "[coordination]" in ctx
    assert "session detai" in ctx  # truncated session id "detail-a" -> "detai"
    assert "Bash" in ctx
    assert "pytest tests/ -v" in ctx


async def test_coordination_reinjection_after_staleness(client):
    """Verify re-injection fires when coordination_last_injected is stale."""
    # Session A starts and has tool activity
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "reinject-a",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    await client.post(
        "/hooks/post-tool-use",
        json={
            "session_id": "reinject-a",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "/reinject-project/src/foo.py"},
            "tool_response": {"success": True},
            "tool_use_id": "tu-reinject-1",
        },
    )

    # Session B starts (startup) — first UserPromptSubmit injects full context
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "reinject-b",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    first = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "reinject-b",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "First prompt",
        },
    )
    assert first.status_code == 200
    first_ctx = first.json().get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "[coordination]" in first_ctx

    # Second prompt — coordination_last_injected is None so it should re-inject
    second = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "reinject-b",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Second prompt",
        },
    )
    assert second.status_code == 200
    second_ctx = second.json().get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "[coordination update]" in second_ctx

    # Third prompt — coordination_last_injected was just set, should be skipped
    third = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "reinject-b",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/reinject-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Third prompt",
        },
    )
    assert third.status_code == 200
    assert third.json() == {}


async def test_coordination_skipped_when_solo(client):
    """Solo session gets no coordination block at all."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "solo-session",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/solo-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "solo-session",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/solo-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "resume",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    ctx = body.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "coordination" not in ctx


async def test_task_completed_upserts_context(client):
    """TaskCompleted upserts completed_tasks project context key."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "task-complete-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/task-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )

    # Fire TaskCompleted
    response = await client.post(
        "/hooks/task-completed",
        json={
            "session_id": "task-complete-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/task-project",
            "permission_mode": "default",
            "hook_event_name": "TaskCompleted",
            "task_id": "task-001",
            "task_subject": "Implement auth",
            "teammate_name": "alpha",
            "team_name": "backend",
        },
    )
    assert response.status_code == 200

    # Verify completed_tasks context key exists via context API
    ctx_response = await client.get("/context", params={"cwd": "/task-project"})
    assert ctx_response.status_code == 200
    contexts = ctx_response.json()
    completed = [c for c in contexts if c["key"] == "completed_tasks"]
    assert len(completed) == 1
    assert completed[0]["value"][0]["subject"] == "Implement auth"

    # A new session should see the completed_tasks in project context
    prompt_resp = await client.post(
        "/hooks/user-prompt",
        json={
            "session_id": "task-complete-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/task-project",
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Hello",
        },
    )
    assert prompt_resp.status_code == 200
    ctx = prompt_resp.json().get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "completed_tasks" in ctx
