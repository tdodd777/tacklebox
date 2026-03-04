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
