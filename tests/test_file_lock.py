async def test_file_lock_warns_on_conflict(client):
    """PreToolUse warns when another session recently edited the same file."""
    # Session A writes a file
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-a",
            "transcript_path": "/tmp/a.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    await client.post(
        "/hooks/post-tool-use",
        json={
            "session_id": "session-a",
            "transcript_path": "/tmp/a.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_use_id": "tu-1",
            "tool_input": {"file_path": "/project/src/api.py", "content": "..."},
            "tool_response": {"filePath": "/project/src/api.py", "success": True},
        },
    )

    # Session B tries to edit the same file
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-b",
            "transcript_path": "/tmp/b.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/pre-tool-use",
        json={
            "session_id": "session-b",
            "transcript_path": "/tmp/b.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_use_id": "tu-2",
            "tool_input": {
                "file_path": "/project/src/api.py",
                "old_string": "x",
                "new_string": "y",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    specific = body.get("hookSpecificOutput", {})
    assert specific.get("permissionDecision") == "allow"
    assert "session-a" in specific.get("additionalContext", "")


async def test_no_warning_without_conflict(client):
    """PreToolUse returns no warning when no other session edited the file."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "session-solo",
            "transcript_path": "/tmp/s.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/pre-tool-use",
        json={
            "session_id": "session-solo",
            "transcript_path": "/tmp/s.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_use_id": "tu-3",
            "tool_input": {"file_path": "/project/src/new_file.py", "content": "..."},
        },
    )
    assert response.status_code == 200
    body = response.json()
    specific = body.get("hookSpecificOutput", {})
    assert specific.get("permissionDecision") is None or body == {}
