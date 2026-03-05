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
    """SessionStart shows other active sessions count."""
    # Create two sessions in same cwd
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
