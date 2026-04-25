"""Tests for threaded gateway session keys.

DM/private chats intentionally ignore thread IDs so one private conversation
does not fragment into multiple sessions. Group/channel threads still get their
own session key and start empty.
"""

import pytest
from unittest.mock import patch

from gateway.config import Platform, GatewayConfig
from gateway.session import SessionSource, SessionStore, build_session_key


@pytest.fixture()
def store(tmp_path):
    """SessionStore with no SQLite, for fast unit tests."""
    config = GatewayConfig()
    with patch("gateway.session.SessionStore._ensure_loaded"):
        s = SessionStore(sessions_dir=tmp_path, config=config)
    s._db = None
    s._loaded = True
    return s


def _dm_source(platform=Platform.SLACK, chat_id="D123", thread_id=None, user_id="U1"):
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type="dm",
        user_id=user_id,
        thread_id=thread_id,
    )


def _group_source(platform=Platform.SLACK, chat_id="C456", thread_id=None, user_id="U1"):
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type="group",
        user_id=user_id,
        thread_id=thread_id,
    )


PARENT_HISTORY = [
    {"role": "user", "content": "What's the weather?"},
    {"role": "assistant", "content": "It's sunny and 72°F."},
]


class TestDMThreadSessionKeying:
    """DM thread IDs must not split one private conversation."""

    def test_thread_session_reuses_parent_dm_session(self, store):
        parent_source = _dm_source()
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_source = _dm_source(thread_id="1234567890.000001")
        thread_entry = store.get_or_create_session(thread_source)

        assert build_session_key(thread_source) == build_session_key(parent_source)
        assert thread_entry.session_id == parent_entry.session_id
        assert store.load_transcript(thread_entry.session_id) == PARENT_HISTORY

    def test_thread_message_appends_to_parent_dm_session(self, store):
        parent_source = _dm_source()
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_source = _dm_source(thread_id="1234567890.000001")
        thread_entry = store.get_or_create_session(thread_source)
        store.append_to_transcript(thread_entry.session_id, {
            "role": "user", "content": "thread-only message"
        })

        parent_transcript = store.load_transcript(parent_entry.session_id)
        assert len(parent_transcript) == 3
        assert parent_transcript[-1]["content"] == "thread-only message"

    def test_multiple_dm_threads_share_parent_session(self, store):
        parent_source = _dm_source()
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_a_source = _dm_source(thread_id="1111.000001")
        thread_a_entry = store.get_or_create_session(thread_a_source)
        store.append_to_transcript(thread_a_entry.session_id, {
            "role": "user", "content": "thread A message"
        })

        thread_b_source = _dm_source(thread_id="2222.000002")
        thread_b_entry = store.get_or_create_session(thread_b_source)

        assert thread_a_entry.session_id == parent_entry.session_id
        assert thread_b_entry.session_id == parent_entry.session_id
        transcript = store.load_transcript(thread_b_entry.session_id)
        assert len(transcript) == 3
        assert transcript[-1]["content"] == "thread A message"

    def test_existing_dm_thread_reuses_same_parent_session(self, store):
        parent_source = _dm_source()
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_source = _dm_source(thread_id="1234567890.000001")
        thread_entry = store.get_or_create_session(thread_source)
        store.append_to_transcript(thread_entry.session_id, {
            "role": "user", "content": "follow-up"
        })

        # Get the same thread session again
        thread_entry_again = store.get_or_create_session(thread_source)
        assert thread_entry_again.session_id == thread_entry.session_id
        assert thread_entry_again.session_id == parent_entry.session_id

        transcript = store.load_transcript(thread_entry_again.session_id)
        assert len(transcript) == 3
        assert transcript[-1]["content"] == "follow-up"


class TestDMThreadIsolationEdgeCases:
    """Edge cases — threads always start empty regardless of context."""

    def test_group_thread_starts_empty(self, store):
        """Group/channel threads should also start empty."""
        parent_source = _group_source()
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_source = _group_source(thread_id="1234567890.000001")
        thread_entry = store.get_or_create_session(thread_source)

        thread_transcript = store.load_transcript(thread_entry.session_id)
        assert len(thread_transcript) == 0

    def test_thread_without_parent_session_starts_empty(self, store):
        """A DM thread with no prior DM history starts empty because the DM session is new."""
        thread_source = _dm_source(thread_id="1234567890.000001")
        thread_entry = store.get_or_create_session(thread_source)

        thread_transcript = store.load_transcript(thread_entry.session_id)
        assert len(thread_transcript) == 0

    def test_dm_without_thread_starts_empty(self, store):
        """Top-level DMs (no thread_id) should start empty as always."""
        source = _dm_source()
        entry = store.get_or_create_session(source)

        transcript = store.load_transcript(entry.session_id)
        assert len(transcript) == 0


class TestDMThreadIsolationCrossPlatform:
    """Verify DM thread keying is consistent across all platforms."""

    @pytest.mark.parametrize(
        "platform",
        [Platform.SLACK, Platform.TELEGRAM, Platform.DISCORD, Platform.MATTERMOST],
    )
    def test_thread_reuses_parent_dm_session_across_platforms(self, store, platform):
        parent_source = _dm_source(platform=platform)
        parent_entry = store.get_or_create_session(parent_source)
        for msg in PARENT_HISTORY:
            store.append_to_transcript(parent_entry.session_id, msg)

        thread_source = _dm_source(platform=platform, thread_id="thread_123")
        thread_entry = store.get_or_create_session(thread_source)

        assert thread_entry.session_id == parent_entry.session_id
        assert store.load_transcript(thread_entry.session_id) == PARENT_HISTORY
