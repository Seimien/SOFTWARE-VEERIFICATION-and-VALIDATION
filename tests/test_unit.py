import pytest
from unittest.mock import Mock
from notification_engine import NotificationEngine


@pytest.fixture
def mock_repo():
    return Mock()


@pytest.fixture
def mock_primary():
    return Mock()


@pytest.fixture
def mock_backup():
    return Mock()


@pytest.fixture
def engine(mock_repo, mock_primary, mock_backup):
    return NotificationEngine(mock_repo, mock_primary, mock_backup)


# ---------------------------------------------------------------------------
# Validation Boundary Test
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("phone", ["+250780000000"])
def test_valid_phone_number_passes_validation(engine, mock_repo, mock_primary, phone):
    mock_repo.get_status.return_value = None
    mock_primary.send_sms.return_value = True

    result = engine.dispatch("msg1", phone, "hello")

    assert result == "SENT_PRIMARY"


@pytest.mark.parametrize("phone", ["0780000000", "+00012"])
def test_invalid_phone_number_raises_without_touching_repo(engine, mock_repo, mock_primary, phone):
    with pytest.raises(ValueError, match="Invalid E.164 phone number format"):
        engine.dispatch("msg1", phone, "hello")

    # Must fail fast: no database call should ever occur for a bad number
    mock_repo.get_status.assert_not_called()
    mock_repo.save_status.assert_not_called()
    mock_primary.send_sms.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency Mock Check
# ---------------------------------------------------------------------------
def test_already_sent_message_is_not_resent(engine, mock_repo, mock_primary):
    mock_repo.get_status.return_value = "SENT"

    result = engine.dispatch("msg1", "+250780000000", "hello")

    assert result == "ALREADY_SENT"
    mock_primary.send_sms.assert_not_called()


# ---------------------------------------------------------------------------
# Retry Logic Verification
# ---------------------------------------------------------------------------
def test_primary_gateway_retries_and_succeeds_on_second_attempt(engine, mock_repo, mock_primary):
    mock_repo.get_status.return_value = None
    mock_primary.send_sms.side_effect = [Exception("network blip"), True]

    result = engine.dispatch("msg1", "+250780000000", "hello")

    assert result == "SENT_PRIMARY"
    assert mock_primary.send_sms.call_count == 2
    mock_repo.save_status.assert_called_once_with("msg1", "+250780000000", "SENT")


# ---------------------------------------------------------------------------
# Fallback Gateway Failover
# ---------------------------------------------------------------------------
def test_backup_gateway_used_when_primary_fails_twice(engine, mock_repo, mock_primary, mock_backup):
    mock_repo.get_status.return_value = None
    mock_primary.send_sms.side_effect = Exception("down")
    mock_backup.send_sms.return_value = True

    result = engine.dispatch("msg1", "+250780000000", "hello")

    assert result == "SENT_BACKUP"
    assert mock_primary.send_sms.call_count == 2
    mock_repo.save_status.assert_called_once_with("msg1", "+250780000000", "SENT_BACKUP")


# ---------------------------------------------------------------------------
# Complete Failure Path
# ---------------------------------------------------------------------------
def test_all_gateways_fail_marks_failed_and_raises(engine, mock_repo, mock_primary, mock_backup):
    mock_repo.get_status.return_value = None
    mock_primary.send_sms.side_effect = Exception("down")
    mock_backup.send_sms.side_effect = Exception("also down")

    with pytest.raises(RuntimeError, match="All gateways failed to deliver message"):
        engine.dispatch("msg1", "+250780000000", "hello")

    mock_repo.save_status.assert_called_once_with("msg1", "+250780000000", "FAILED")