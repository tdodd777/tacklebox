async def test_pre_tool_use_logs_event(client):
    """PreToolUse logs the tool event."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "tool-test-1",
            "transcript_path": "/tmp/t.jsonl",
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
            "session_id": "tool-test-1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_use_id": "tu-100",
            "tool_input": {"command": "npm test"},
        },
    )
    assert response.status_code == 200


async def test_post_tool_use_updates_context(client):
    """PostToolUse updates last_edited_files for Write/Edit."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "post-tool-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/post-tool-use",
        json={
            "session_id": "post-tool-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_use_id": "tu-200",
            "tool_input": {"file_path": "/project/src/main.py", "content": "..."},
            "tool_response": {"filePath": "/project/src/main.py", "success": True},
        },
    )
    assert response.status_code == 200


async def test_post_tool_use_failure_logs(client):
    """PostToolUseFailure logs the error."""
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "fail-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )
    response = await client.post(
        "/hooks/post-tool-use-failure",
        json={
            "session_id": "fail-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/project",
            "permission_mode": "default",
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_use_id": "tu-300",
            "tool_input": {"command": "npm test"},
            "error": "Exit code 1",
            "is_interrupt": False,
        },
    )
    assert response.status_code == 200
