"""Session-store persistence for pending manual compression retry gates."""

from datetime import datetime

from gateway.config import Platform
from gateway.session import SessionEntry


def test_session_entry_persists_pending_compression_retry_gate():
    entry = SessionEntry(
        session_key="agent:main:qqbot:dm:123",
        session_id="session-1",
        created_at=datetime(2026, 1, 1, 1, 2, 3),
        updated_at=datetime(2026, 1, 1, 1, 2, 4),
        platform=Platform.QQBOT,
        compression_retry_pending={
            "error": "401 token invalidated",
            "attempts": 2,
            "max_attempts": 3,
        },
    )

    data = entry.to_dict()
    assert data["compression_retry_pending"]["error"] == "401 token invalidated"

    restored = SessionEntry.from_dict(data)
    assert restored.compression_retry_pending == {
        "error": "401 token invalidated",
        "attempts": 2,
        "max_attempts": 3,
    }
