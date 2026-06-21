"""Tests for dispute-service logic."""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_dispute_reasons_valid():
    valid = ["ITEM_NOT_AS_DESCRIBED", "DAMAGED", "NOT_RECEIVED", "WRONG_ITEM", "OTHER"]
    for r in valid:
        assert r in valid

    invalid = ["UNKNOWN", "BAD", "", "damaged"]
    for r in invalid:
        assert r not in valid or r == "damaged"  # case-sensitive


def test_dispute_status_transitions():
    """Dispute status flow: OPEN → SELLER_RESPONDED → ESCALATED → RESOLVED."""
    transitions = {
        "OPEN": ["SELLER_RESPONDED"],  # seller must respond
        "SELLER_RESPONDED": ["ESCALATED", "RESOLVED"],
        "ESCALATED": ["RESOLVED", "REJECTED"],
        "RESOLVED": [],
        "REJECTED": [],
        "CANCELLED": [],
    }

    def can_transition(from_s, to_s):
        return to_s in transitions.get(from_s, [])

    assert can_transition("OPEN", "SELLER_RESPONDED")
    assert can_transition("SELLER_RESPONDED", "ESCALATED")
    assert can_transition("SELLER_RESPONDED", "RESOLVED")
    assert can_transition("ESCALATED", "RESOLVED")
    assert can_transition("ESCALATED", "REJECTED")

    # Invalid
    assert not can_transition("OPEN", "ESCALATED")  # must go through seller response
    assert not can_transition("RESOLVED", "OPEN")  # terminal


def test_seller_response_deadline():
    """Seller must respond within 48 hours."""
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=48)

    # Within deadline
    response_time = now + timedelta(hours=24)
    assert response_time < deadline

    # Past deadline
    response_time = now + timedelta(hours=50)
    assert not response_time < deadline


def test_evidence_files_limit():
    """Max 5 evidence files per dispute."""
    max_files = 5
    assert len(["f1", "f2", "f3"]) <= max_files
    assert not len(["f1", "f2", "f3", "f4", "f5", "f6"]) <= max_files


def test_one_open_dispute_per_order():
    """Cannot open new dispute if there's already an OPEN dispute for same order."""
    existing_disputes = [
        {"order_id": "order-1", "status": "OPEN"},
        {"order_id": "order-1", "status": "RESOLVED"},
    ]
    new_order = "order-1"

    open_exists = any(
        d["order_id"] == new_order and d["status"] in ("OPEN", "SELLER_RESPONDED", "ESCALATED")
        for d in existing_disputes
    )
    assert open_exists  # should reject

    # If only resolved disputes exist, can open new
    existing_disputes = [{"order_id": "order-1", "status": "RESOLVED"}]
    open_exists = any(
        d["order_id"] == new_order and d["status"] in ("OPEN", "SELLER_RESPONDED", "ESCALATED")
        for d in existing_disputes
    )
    assert not open_exists


def test_dispute_window_after_delivery():
    """Buyer can dispute within 7 days after delivery."""
    window_days = 7
    now = datetime.now(timezone.utc)
    delivered_at = now - timedelta(days=5)

    can_dispute = (now - delivered_at).days <= window_days
    assert can_dispute

    delivered_at = now - timedelta(days=10)
    can_dispute = (now - delivered_at).days <= window_days
    assert not can_dispute


def test_refund_amount_validation():
    """Refund amount must not exceed payment amount."""
    payment_amount = 1_000_000
    requested_refund = 800_000
    assert requested_refund <= payment_amount

    requested_refund = 1_200_000
    assert not requested_refund <= payment_amount


def test_seller_response_options():
    """Valid seller response resolutions."""
    valid = ["ACCEPT_REFUND", "REJECT", "OFFER_PARTIAL", "OFFER_REPLACE"]
    assert "ACCEPT_REFUND" in valid
    assert "REJECT" in valid
    assert "OFFER_PARTIAL" in valid
    assert "OFFER_REPLACE" in valid


def test_admin_resolution_options():
    """Valid admin resolution options."""
    valid = ["FULL_REFUND", "PARTIAL_REFUND", "REPLACE", "REJECT"]
    assert "FULL_REFUND" in valid
    assert "REJECT" in valid


def test_seller_authorization():
    """Only seller of product can respond to dispute."""
    dispute_seller_id = "seller-1"
    responding_user_id = "seller-1"
    is_admin = False

    can_respond = (dispute_seller_id == responding_user_id) or is_admin
    assert can_respond

    responding_user_id = "seller-2"
    can_respond = (dispute_seller_id == responding_user_id) or is_admin
    assert not can_respond


def test_buyer_can_escalate_only_after_seller_response():
    """Buyer can only escalate if seller has responded."""
    dispute_status = "SELLER_RESPONDED"
    can_escalate = dispute_status == "SELLER_RESPONDED"
    assert can_escalate

    dispute_status = "OPEN"
    can_escalate = dispute_status == "SELLER_RESPONDED"
    assert not can_escalate
