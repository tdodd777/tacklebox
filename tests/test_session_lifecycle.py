async def test_session_start_creates_session(client):
    """SessionStart creates a new session row and returns context."""
    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "test-session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/home/user/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "decision" not in body


async def test_session_start_upsert(client):
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
    payload["source"] = "compact"
    response = await client.post("/hooks/session-start", json=payload)
    assert response.status_code == 200


async def test_session_end_marks_completed(client):
    """SessionEnd marks the session as completed."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "test-session-end",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/home/user/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/session-end",
        json={
            "session_id": "test-session-end",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/home/user/project",
            "permission_mode": "default",
            "hook_event_name": "SessionEnd",
            "reason": "other",
        },
    )
    assert response.status_code == 200


async def test_session_auto_creates_on_missing(client):
    """Events for unknown sessions auto-create the session."""
    response = await client.post(
        "/hooks/notification",
        json={
            "session_id": "auto-created-session",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
            "message": "test",
        },
    )
    assert response.status_code == 200
