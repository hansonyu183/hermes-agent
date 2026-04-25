"""Tests for Mattermost channel_skill_bindings auto-skill resolution."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform


def _make_adapter(extra=None):
    from gateway.platforms.mattermost import MattermostAdapter

    adapter = object.__new__(MattermostAdapter)
    adapter.config = MagicMock()
    adapter.config.extra = extra or {}
    adapter.platform = Platform.MATTERMOST
    adapter._bot_user_id = "bot-user"
    adapter._bot_username = "hermes"
    adapter._dedup = MagicMock()
    adapter._dedup.is_duplicate.return_value = False
    adapter.handle_message = AsyncMock()
    adapter._api_get = AsyncMock()
    adapter._session = MagicMock()
    adapter._token = "token"
    adapter._base_url = "https://mattermost.example.com"
    return adapter


def _posted_event(post, *, channel_type="O", sender_name="@alice"):
    return {
        "event": "posted",
        "data": {
            "post": json.dumps(post),
            "channel_type": channel_type,
            "sender_name": sender_name,
        },
    }


@pytest.mark.asyncio
async def test_channel_binding_sets_auto_skill_on_new_channel_thread(monkeypatch):
    adapter = _make_adapter(
        {
            "channel_skill_bindings": [
                {"id": "channel-1", "skills": ["channel-skill", "shared-skill"]},
            ]
        }
    )
    monkeypatch.setenv("MATTERMOST_REQUIRE_MENTION", "false")

    await adapter._handle_ws_event(
        _posted_event(
            {
                "id": "post-1",
                "channel_id": "channel-1",
                "user_id": "user-1",
                "message": "hello from channel",
            }
        )
    )

    event = adapter.handle_message.await_args.args[0]
    assert event.auto_skill == ["channel-skill", "shared-skill"]
    assert event.source.chat_id == "channel-1"
    assert event.source.thread_id == "post-1"


@pytest.mark.asyncio
async def test_thread_binding_overrides_channel_binding(monkeypatch):
    adapter = _make_adapter(
        {
            "channel_skill_bindings": [
                {"id": "channel-1", "skills": ["channel-skill", "shared-skill"]},
                {"id": "thread-1", "skills": ["thread-skill", "shared-skill", "thread-skill"]},
            ]
        }
    )
    monkeypatch.setenv("MATTERMOST_REQUIRE_MENTION", "false")

    await adapter._handle_ws_event(
        _posted_event(
            {
                "id": "reply-1",
                "root_id": "thread-1",
                "channel_id": "channel-1",
                "user_id": "user-1",
                "message": "hello from thread",
            }
        )
    )

    event = adapter.handle_message.await_args.args[0]
    assert event.auto_skill == ["thread-skill", "shared-skill"]
    assert event.source.chat_id == "channel-1"
    assert event.source.thread_id == "thread-1"
