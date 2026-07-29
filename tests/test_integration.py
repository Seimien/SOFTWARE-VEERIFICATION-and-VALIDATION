import sqlite3
import pytest
from unittest.mock import Mock
from notification_engine import NotificationEngine, WalletRepository, SMSGatewayClient


# ---------------------------------------------------------------------------
# Real SQLite-backed repository (the thing under test in this file)
# ---------------------------------------------------------------------------
class SqliteWalletRepository(WalletRepository):
    def __init__(self, conn):
        self.conn = conn

    def get_status(self, msg_id: str) -> str:
        cur = self.conn.execute(
            "SELECT status FROM messages WHERE msg_id = ?", (msg_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def save_status(self, msg_id: str, phone: str, status: str):
        self.conn.execute(
            "INSERT INTO messages (msg_id, phone, status) VALUES (?, ?, ?)",
            (msg_id, phone, status),
        )
        self.conn.commit()


# A deliberately buggy repository: writes to the WRONG table (msg_logs
# instead of messages). This is what "Mock Lie" is demonstrating.
class BuggyWalletRepository(WalletRepository):
    def __init__(self, conn):
        self.conn = conn

    def get_status(self, msg_id: str) -> str:
        cur = self.conn.execute(
            "SELECT status FROM messages WHERE msg_id = ?", (msg_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def save_status(self, msg_id: str, phone: str, status: str):
        # BUG: wrong table name, would only be caught by real DB integration tests
        self.conn.execute(
            "INSERT INTO msg_logs (msg_id, phone, status) VALUES (?, ?, ?)",
            (msg_id, phone, status),
        )
        self.conn.commit()


class FakeGateway(SMSGatewayClient):
    def send_sms(self, phone: str, message: str) -> bool:
        return True


@pytest.fixture
def sqlite_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE messages (msg_id TEXT, phone TEXT, status TEXT)"
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Real, successful dispatch against real SQLite
# ---------------------------------------------------------------------------
def test_successful_dispatch_persists_sent_status_in_sqlite(sqlite_conn):
    repo = SqliteWalletRepository(sqlite_conn)
    engine = NotificationEngine(repo, FakeGateway())

    result = engine.dispatch("msg1", "+250780000000", "hello")

    assert result == "SENT_PRIMARY"
    row = sqlite_conn.execute(
        "SELECT status FROM messages WHERE msg_id = ?", ("msg1",)
    ).fetchone()
    assert row is not None
    assert row[0] == "SENT"


# ---------------------------------------------------------------------------
# The "Mock Lie": a unit test with Mocks is happy to lie to you, because
# Mock objects don't know or care what table name a real SQL statement uses.
# Only an integration test against a real database exposes the bug.
# ---------------------------------------------------------------------------
def test_mock_lie_unit_test_passes_with_buggy_repo():
    """Unit test using a Mock: passes even though save_status is buggy,
    because the mock has no concept of 'messages' vs 'msg_logs' tables."""
    mock_repo = Mock()
    mock_primary = Mock()
    mock_primary.send_sms.return_value = True
    mock_repo.get_status.return_value = None

    engine = NotificationEngine(mock_repo, mock_primary)
    result = engine.dispatch("msg1", "+250780000000", "hello")

    assert result == "SENT_PRIMARY"
    # The mock happily "confirms" save_status was called correctly.
    mock_repo.save_status.assert_called_once_with("msg1", "+250780000000", "SENT")
    # <-- This test is green, yet the real implementation could still be broken.


def test_mock_lie_integration_test_fails_with_buggy_repo(sqlite_conn):
    """Integration test using a real SQLite DB: exposes that the buggy
    repository writes to a table that doesn't exist, so 'messages' never
    gets the SENT row the unit test claimed was saved."""
    repo = BuggyWalletRepository(sqlite_conn)
    engine = NotificationEngine(repo, FakeGateway())

    # The buggy repo's INSERT targets a nonexistent table, so this raises
    # an OperationalError instead of silently succeeding.
    with pytest.raises(sqlite3.OperationalError, match="no such table: msg_logs"):
        engine.dispatch("msg1", "+250780000000", "hello")

    # And critically: the real 'messages' table was never populated,
    # proving the unit test's "pass" was a lie about real behavior.
    row = sqlite_conn.execute(
        "SELECT status FROM messages WHERE msg_id = ?", ("msg1",)
    ).fetchone()
    assert row is None