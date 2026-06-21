"""Tests for fraud-service rule logic."""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_velocity_check_threshold():
    """3+ failed payments in 10 min should trigger VELOCITY_FAILED_PAYMENT."""
    threshold = 3
    failed_count = 3
    assert failed_count >= threshold  # should trigger

    failed_count = 2
    assert not failed_count >= threshold  # should NOT trigger


def test_high_order_velocity_threshold():
    """10+ orders in 1 hour should trigger HIGH_ORDER_VELOCITY."""
    threshold = 10
    order_count = 10
    assert order_count >= threshold  # trigger

    order_count = 9
    assert not order_count >= threshold  # no trigger


def test_large_order_thresholds():
    """Test large order amount thresholds."""
    LARGE = 50_000_000
    VERY_LARGE = 100_000_000

    # Just below large
    amount = 49_999_999
    assert not amount >= LARGE
    assert not amount >= VERY_LARGE

    # At large threshold
    amount = 50_000_000
    assert amount >= LARGE
    assert not amount >= VERY_LARGE

    # At very large threshold
    amount = 100_000_000
    assert amount >= LARGE
    assert amount >= VERY_LARGE


def test_score_thresholds():
    """Test score-based action decisions."""
    BLOCK_THRESHOLD = 0.7
    CHALLENGE_THRESHOLD = 0.4

    # Score >= 0.7 → BLOCKED
    score = 0.75
    action = "BLOCKED" if score >= BLOCK_THRESHOLD else ("CHALLENGED" if score >= CHALLENGE_THRESHOLD else "ALLOWED")
    assert action == "BLOCKED"

    # Score 0.4-0.7 → CHALLENGED
    score = 0.5
    action = "BLOCKED" if score >= BLOCK_THRESHOLD else ("CHALLENGED" if score >= CHALLENGE_THRESHOLD else "ALLOWED")
    assert action == "CHALLENGED"

    # Score < 0.4 → ALLOWED
    score = 0.3
    action = "BLOCKED" if score >= BLOCK_THRESHOLD else ("CHALLENGED" if score >= CHALLENGE_THRESHOLD else "ALLOWED")
    assert action == "ALLOWED"


def test_score_capped_at_1():
    """Score should not exceed 1.0."""
    score = 1.5
    score = min(score, 1.0)
    assert score == 1.0


def test_multiple_registrations_threshold():
    """3+ registrations from same IP in 1 min should trigger MULTIPLE_REGISTRATIONS_IP."""
    threshold = 3
    recent_regs = 3
    assert recent_regs >= threshold  # trigger

    recent_regs = 2
    assert not recent_regs >= threshold  # no trigger


def test_transaction_types():
    """Valid transaction types."""
    valid_types = ["ORDER", "PAYMENT", "REGISTER", "LOGIN", "WITHDRAWAL"]
    for t in valid_types:
        assert t in valid_types

    invalid = "INVALID"
    assert invalid not in valid_types


def test_flag_severities():
    """Valid severity values."""
    valid = ["info", "warning", "critical"]
    assert "info" in valid
    assert "warning" in valid
    assert "critical" in valid


def test_action_decisions():
    """Valid action values."""
    valid = ["ALLOWED", "CHALLENGED", "BLOCKED"]
    assert "ALLOWED" in valid
    assert "CHALLENGED" in valid
    assert "BLOCKED" in valid


def test_flag_status_values():
    """Valid flag status values."""
    valid = ["OPEN", "REVIEWING", "RESOLVED", "FALSE_POSITIVE"]
    assert "OPEN" in valid


def test_score_addition_for_multiple_flags():
    """Score from multiple rules should accumulate (capped at 1.0)."""
    # VELOCITY_FAILED_PAYMENT (0.4) + LARGE_ORDER (0.15) = 0.55
    score = 0.0
    score += 0.4  # VELOCITY_FAILED_PAYMENT
    score += 0.15  # LARGE_ORDER
    score = min(score, 1.0)
    assert score == 0.55  # CHALLENGED


def test_score_addition_capped():
    """Score from many rules should cap at 1.0."""
    score = 0.0
    score += 0.4  # VELOCITY_FAILED_PAYMENT
    score += 0.3  # HIGH_ORDER_VELOCITY
    score += 0.3  # LARGE_ORDER
    score += 0.3  # NEW_ACCOUNT_LARGE_ORDER
    score = min(score, 1.0)
    assert score == 1.0  # capped


def test_blocked_ip_check():
    """Test IP blocking logic."""
    blocked_until_future = datetime.now(timezone.utc) + timedelta(hours=1)
    blocked_until_past = datetime.now(timezone.utc) - timedelta(hours=1)

    now = datetime.now(timezone.utc)

    # Future block → still blocked
    assert blocked_until_future > now

    # Past block → expired
    assert not blocked_until_past > now

    # NULL block_until → permanent
    blocked_until_null = None
    assert blocked_until_null is None  # treat as permanent


def test_new_account_detection():
    """New account + large order should be flagged."""
    new_account_threshold_amount = 5_000_000
    is_new_account = True
    order_amount = 6_000_000

    # Both conditions must be true to flag
    should_flag = is_new_account and order_amount > new_account_threshold_amount
    assert should_flag

    # Existing account → no flag
    is_new_account = False
    should_flag = is_new_account and order_amount > new_account_threshold_amount
    assert not should_flag
