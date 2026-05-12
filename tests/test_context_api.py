async def test_put_context_honors_scope_field(client):
    """PUT /context with scope=session writes a session-scoped row, distinct from project scope.

    Project and session scopes use separate partial unique indexes, so the same
    (cwd, key) pair can exist in both scopes with different values. Verify the
    handler routes to the right scope and the two values stay isolated.
    """
    await client.post(
        "/hooks/session-start",
        json={
            "session_id": "scope-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/scope-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )

    # Same key, same cwd, different scopes, different values.
    await client.put(
        "/context",
        json={
            "cwd": "/scope-project",
            "session_id": "scope-test",
            "key": "notes",
            "value": "session-only data",
            "scope": "session",
        },
    )
    await client.put(
        "/context",
        json={
            "cwd": "/scope-project",
            "session_id": "scope-test",
            "key": "notes",
            "value": "project-wide data",
        },
    )

    session_rows = (
        await client.get(
            "/context", params={"cwd": "/scope-project", "scope": "session"}
        )
    ).json()
    project_rows = (
        await client.get(
            "/context", params={"cwd": "/scope-project", "scope": "project"}
        )
    ).json()

    session_notes = [r for r in session_rows if r["key"] == "notes"]
    project_notes = [r for r in project_rows if r["key"] == "notes"]

    assert len(session_notes) == 1
    assert session_notes[0]["value"] == "session-only data"
    assert len(project_notes) == 1
    assert project_notes[0]["value"] == "project-wide data"


async def test_put_context_rejects_invalid_scope(client):
    """An unsupported scope value is rejected by pydantic before the handler runs."""
    response = await client.put(
        "/context",
        json={
            "cwd": "/scope-project",
            "session_id": "scope-test",
            "key": "notes",
            "value": "x",
            "scope": "user",
        },
    )
    assert response.status_code == 422
