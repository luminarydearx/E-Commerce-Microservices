"""Unit tests for domain types (order state machine)."""
import pytest

from ecommerce.order-service.internal/domain import OrderStatus


class TestOrderStateMachine:
    def test_pending_can_be_paid(self):
        assert OrderStatus("PENDING").CanTransitionTo(OrderStatus("PAID")) is True

    def test_pending_can_be_cancelled(self):
        assert OrderStatus("PENDING").CanTransitionTo(OrderStatus("CANCELLED")) is True

    def test_paid_can_be_confirmed(self):
        assert OrderStatus("PAID").CanTransitionTo(OrderStatus("CONFIRMED")) is True

    def test_paid_cannot_be_pending(self):
        assert OrderStatus("PAID").CanTransitionTo(OrderStatus("PENDING")) is False

    def test_completed_is_terminal(self):
        # Cannot transition to anything
        for target in OrderStatus:
            if target != OrderStatus("COMPLETED"):
                assert OrderStatus("COMPLETED").CanTransitionTo(target) is False

    def test_cancelled_is_terminal(self):
        for target in OrderStatus:
            if target != OrderStatus("CANCELLED"):
                assert OrderStatus("CANCELLED").CanTransitionTo(target) is False

    def test_unknown_status(self):
        # Status not in ValidTransitions returns False
        assert OrderStatus("UNKNOWN").CanTransitionTo(OrderStatus("PENDING")) is False
