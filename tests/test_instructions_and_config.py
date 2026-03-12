async def test_instructions_loaded(client):
    """InstructionsLoaded logs the event and returns {}."""
    response = await client.post(
        "/hooks/instructions-loaded",
        json={
            "session_id": "test-instructions-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/home/user/project",
            "permission_mode": "default",
            "hook_event_name": "InstructionsLoaded",
            "file_path": "/home/user/project/CLAUDE.md",
            "memory_type": "Project",
            "load_reason": "session_start",
        },
    )
    assert response.status_code == 200
    assert response.json() == {}

    # Verify event was recorded
    events = await client.get("/sessions")
    sessions = events.json()
    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    events_resp = await client.get(f"/sessions/{session_id}/events")
    events_data = events_resp.json()
    assert len(events_data) == 1
    assert events_data[0]["hook_event"] == "InstructionsLoaded"
    assert events_data[0]["tool_input"]["file_path"] == "/home/user/project/CLAUDE.md"
    assert events_data[0]["tool_input"]["memory_type"] == "Project"


async def test_config_change(client):
    """ConfigChange logs the event and returns {}."""
    response = await client.post(
        "/hooks/config-change",
        json={
            "session_id": "test-config-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/home/user/project",
            "permission_mode": "default",
            "hook_event_name": "ConfigChange",
            "source": "project_settings",
            "file_path": "/home/user/project/.claude/settings.json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {}

    # Verify event was recorded
    events = await client.get("/sessions")
    sessions = events.json()
    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    events_resp = await client.get(f"/sessions/{session_id}/events")
    events_data = events_resp.json()
    assert len(events_data) == 1
    assert events_data[0]["hook_event"] == "ConfigChange"
    assert events_data[0]["tool_input"]["source"] == "project_settings"
