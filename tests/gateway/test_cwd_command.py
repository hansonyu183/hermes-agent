"""Tests for gateway /cwd command and runtime channel cwd resolution."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, resolve_channel_cwd
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.MATTERMOST,
        user_id="u1",
        user_name="hanson",
        chat_id="channel-1",
        chat_type="channel",
        thread_id="thread-1",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner(session_db):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.MATTERMOST: PlatformConfig(enabled=True, token="***")}
    )
    runner.adapters = {Platform.MATTERMOST: MagicMock(send=AsyncMock())}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._show_reasoning = False
    runner._session_db = session_db
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context, session_cwd="": None
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._send_voice_reply = AsyncMock()
    runner._capture_gateway_honcho_if_configured = lambda *args, **kwargs: None
    runner._emit_gateway_run_progress = AsyncMock()
    runner._draining = False
    runner._update_prompt_pending = {}
    runner._background_tasks = set()
    session_entry = SessionEntry(
        session_key=build_session_key(_make_source()),
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.MATTERMOST,
        chat_type="channel",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.rewrite_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()
    return runner


@pytest.mark.asyncio
async def test_cwd_set_and_clear_command_roundtrip(tmp_path, monkeypatch):
    from hermes_state import SessionDB

    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path / "global"))
    project_dir = tmp_path / "project-a"
    project_dir.mkdir()
    session_db = SessionDB(db_path=tmp_path / "state.db")
    runner = _make_runner(session_db)

    result = await runner._handle_message(_make_event(f"/cwd {project_dir}"))

    assert "set for this channel" in result.lower()
    assert session_db.resolve_channel_cwd("mattermost", "channel-1", thread_id="thread-1") == str(project_dir)

    status = await runner._handle_message(_make_event("/cwd"))
    assert str(project_dir) in status
    assert "dynamic binding" in status.lower()

    cleared = await runner._handle_message(_make_event("/cwd clear"))
    assert "cleared" in cleared.lower()
    assert session_db.resolve_channel_cwd("mattermost", "channel-1", thread_id="thread-1") is None

    session_db.close()


@pytest.mark.asyncio
async def test_cwd_stores_filesystem_canonical_case(tmp_path):
    from hermes_state import SessionDB

    project_dir = tmp_path / "MyProject"
    project_dir.mkdir()
    session_db = SessionDB(db_path=tmp_path / "state.db")
    runner = _make_runner(session_db)

    entered_path = str(tmp_path / "myproject")
    result = await runner._handle_message(_make_event(f"/cwd {entered_path}"))

    assert "set for this channel" in result.lower()
    assert session_db.resolve_channel_cwd("mattermost", "channel-1", thread_id="thread-1") == str(project_dir)

    session_db.close()


@pytest.mark.asyncio
async def test_cwd_command_is_handled_without_interrupting_running_agent(tmp_path):
    from hermes_state import SessionDB

    project_dir = tmp_path / "project-a"
    project_dir.mkdir()
    session_db = SessionDB(db_path=tmp_path / "state.db")
    runner = _make_runner(session_db)
    running_agent = MagicMock()
    session_key = build_session_key(_make_source())
    runner._running_agents[session_key] = running_agent
    runner._running_agents_ts[session_key] = 0

    result = await runner._handle_message(_make_event(f"/cwd {project_dir}"))

    assert "set for this channel" in result.lower()
    running_agent.interrupt.assert_not_called()
    session_db.close()


def test_runtime_channel_cwd_overrides_static_config(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    import gateway.platforms.base as base_mod

    runtime_db = SessionDB(db_path=tmp_path / "state.db")
    runtime_db.set_channel_cwd("discord", "123", "/runtime/project")
    monkeypatch.setattr(base_mod, "_CHANNEL_CWD_DB", runtime_db)

    resolved = resolve_channel_cwd(
        {"channel_cwds": {"123": "/config/project"}},
        "123",
        platform="discord",
    )

    assert resolved == "/runtime/project"
    runtime_db.close()


def test_runtime_channel_cwd_resolves_mattermost_thread_binding(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    import gateway.platforms.base as base_mod

    runtime_db = SessionDB(db_path=tmp_path / "state.db")
    runtime_db.set_channel_cwd(
        "mattermost",
        "channel-1",
        "/runtime/thread-project",
        thread_id="thread-1",
    )
    monkeypatch.setattr(base_mod, "_CHANNEL_CWD_DB", runtime_db)

    resolved = resolve_channel_cwd({}, "channel-1", "thread-1", platform="mattermost")

    assert resolved == "/runtime/thread-project"
    runtime_db.close()


def test_runtime_channel_cwd_resolves_discord_thread_binding(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    import gateway.platforms.base as base_mod

    runtime_db = SessionDB(db_path=tmp_path / "state.db")
    runtime_db.set_channel_cwd("discord", "thread-1", "/runtime/thread-project")
    monkeypatch.setattr(base_mod, "_CHANNEL_CWD_DB", runtime_db)

    resolved = resolve_channel_cwd({}, "thread-1", "parent-1", platform="discord")

    assert resolved == "/runtime/thread-project"
    runtime_db.close()


def test_runtime_channel_cwd_resolves_slack_thread_binding(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    import gateway.platforms.base as base_mod

    runtime_db = SessionDB(db_path=tmp_path / "state.db")
    runtime_db.set_channel_cwd(
        "slack",
        "channel-1",
        "/runtime/thread-project",
        thread_id="1712345.6789",
    )
    monkeypatch.setattr(base_mod, "_CHANNEL_CWD_DB", runtime_db)

    resolved = resolve_channel_cwd({}, "channel-1", "1712345.6789", platform="slack")

    assert resolved == "/runtime/thread-project"
    runtime_db.close()
