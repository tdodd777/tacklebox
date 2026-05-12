async def test_handler_exception_returns_empty_200_and_increments_counter(
    client, monkeypatch
):
    """A handler exception is swallowed, 200 is returned, and the counter ticks."""
    from tacklebox import utils
    from tacklebox.routes import hooks_session

    starting_count = utils.fail_open_error_count

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated handler failure")

    monkeypatch.setattr(hooks_session, "build_session_summary", boom)

    response = await client.post(
        "/hooks/session-start",
        json={
            "session_id": "fail-open-test",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/fail-open-project",
            "permission_mode": "default",
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "claude-sonnet-4-6",
        },
    )

    assert response.status_code == 200
    assert response.json() == {}
    assert utils.fail_open_error_count == starting_count + 1
