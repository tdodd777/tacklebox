async def test_stop_allows_when_no_tasks(client):
    """Stop allows when there are no incomplete tasks."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-stop",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/stop",
        json={
            "session_id": "session-stop",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("decision") is None


async def test_stop_blocks_with_incomplete_tasks(client):
    """Stop blocks when there are incomplete tasks."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-block",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/block-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    # Set incomplete tasks
    await client.put(
        "/context",
        json={
            "cwd": "/block-project",
            "session_id": "session-block",
            "key": "incomplete_tasks",
            "value": ["Fix auth bug", "Write tests"],
        },
    )
    response = await client.post(
        "/hooks/stop",
        json={
            "session_id": "session-block",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/block-project",
            "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("decision") == "block"
    assert "incomplete" in body.get("reason", "").lower()


async def test_stop_safety_valve_after_max_blocks(client):
    """Stop allows after STOP_MAX_BLOCKS blocks to prevent infinite loops."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-loop",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/loop-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    # Set incomplete tasks
    await client.put(
        "/context",
        json={
            "cwd": "/loop-project",
            "session_id": "session-loop",
            "key": "incomplete_tasks",
            "value": ["Persistent task"],
        },
    )

    # Hit stop multiple times — should block first few, then safety valve
    for i in range(4):  # STOP_MAX_BLOCKS default is 3
        response = await client.post(
            "/hooks/stop",
            json={
                "session_id": "session-loop",
                "transcript_path": "/tmp/t.jsonl",
                "cwd": "/loop-project",
                "permission_mode": "default",
                "hook_event_name": "Stop",
                "stop_hook_active": i > 0,
                "last_assistant_message": f"Attempt {i}",
            },
        )

    # Last response should allow stop (safety valve)
    assert response.json().get("decision") is None
