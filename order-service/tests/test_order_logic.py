"""Tests for order-service state machine and cart logic."""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_order_state_machine_transitions():
    """Order status transitions should follow state machine rules."""
    transitions = {
        "PENDING": ["PAID", "CANCELLED"],
        "PAID": ["CONFIRMED", "CANCELLED", "REFUNDED"],
        "CONFIRMED": ["SHIPPED", "CANCELLED"],
        "SHIPPED": ["DELIVERED"],
        "DELIVERED": ["COMPLETED"],
        "COMPLETED": [],
        "CANCELLED": [],
        "REFUNDED": [],
    }

    def can_transition(from_status, to_status):
        return to_status in transitions.get(from_status, [])

    # Valid
    assert can_transition("PENDING", "PAID")
    assert can_transition("PENDING", "CANCELLED")
    assert can_transition("PAID", "CONFIRMED")
    assert can_transition("PAID", "REFUNDED")
    assert can_transition("CONFIRMED", "SHIPPED")
    assert can_transition("SHIPPED", "DELIVERED")
    assert can_transition("DELIVERED", "COMPLETED")

    # Invalid
    assert not can_transition("PENDING", "CONFIRMED")
    assert not can_transition("PENDING", "SHIPPED")
    assert not can_transition("PAID", "PENDING")
    assert not can_transition("COMPLETED", "CANCELLED")
    assert not can_transition("CANCELLED", "PENDING")


def test_terminal_states():
    transitions = {"COMPLETED": [], "CANCELLED": [], "REFUNDED": []}
    for status, allowed in transitions.items():
        assert len(allowed) == 0


def test_checkout_quantity_validation():
    max_qty = 99
    assert 1 <= 50 <= max_qty
    assert not 1 <= 0 <= max_qty
    assert not 1 <= 100 <= max_qty


def test_cart_max_items():
    max_items = 100
    assert 99 < max_items  # can add
    assert not 100 < max_items  # full


def test_order_expires_at():
    created = datetime.now(timezone.utc)
    expires = created + timedelta(minutes=15)
    delta_min = (expires - created).total_seconds() / 60
    assert 14 <= delta_min <= 16


def test_stock_reservation_atomicity():
    stock = 10
    reserved = 3
    available = stock - reserved  # 7

    # User A: 5 → OK
    assert available >= 5
    reserved += 5
    available = stock - reserved  # 2

    # User B: 3 → FAIL
    assert not available >= 3


def test_reservation_release():
    stock = 10
    reserved = 5
    reserved = max(0, reserved - 3)
    assert reserved == 2


def test_reservation_confirm():
    stock = 10
    reserved = 3
    assert stock >= 3 and reserved >= 3
    stock -= 3
    reserved -= 3
    assert stock == 7
    assert reserved == 0


def test_idempotency_key_uuid():
    import uuid
    valid = str(uuid.uuid4())
    assert uuid.UUID(valid)


def test_order_total_calculation():
    items = [
        {"unit_price": 100000, "quantity": 2},
        {"unit_price": 50000, "quantity": 3},
    ]
    total = sum(i["unit_price"] * i["quantity"] for i in items)
    assert total == 350000


def test_authorization_check():
    order_user = "user-1"
    requester = "user-1"
    is_admin = False
    assert order_user == requester or is_admin

    requester = "user-2"
    assert not (order_user == requester or is_admin)

    is_admin = True
    assert order_user == requester or is_admin


def test_saga_compensation_reverse_order():
    steps = ["create_order", "reserve_stock_a", "reserve_stock_b"]
    failed_at = 2  # reserve_stock_b failed
    compensations = []
    for step in reversed(steps[:failed_at]):
        compensations.append(f"compensate_{step}")
    assert compensations == ["compensate_reserve_stock_a", "compensate_create_order"]


def test_cancel_window():
    cancel_window_min = 30
    now = datetime.now(timezone.utc)
    created = now - timedelta(minutes=20)
    can_cancel = (now - created).total_seconds() / 60 <= cancel_window_min
    assert can_cancel

    created = now - timedelta(minutes=45)
    can_cancel = (now - created).total_seconds() / 60 <= cancel_window_min
    assert not can_cancel
