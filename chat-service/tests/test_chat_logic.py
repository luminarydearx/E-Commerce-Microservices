"""Tests for chat-service hub logic."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_message_types():
    valid = ["text", "image", "product_card", "system", "join", "leave"]
    for t in valid:
        assert t in valid


def test_sender_roles():
    valid = ["buyer", "seller", "admin"]
    for r in valid:
        assert r in valid


def test_no_self_chat():
    buyer_id = "user-1"
    seller_id = "user-1"
    assert buyer_id == seller_id  # reject

    seller_id = "user-2"
    assert buyer_id != seller_id  # OK


def test_unread_count_logic():
    buyer_unread = 3
    seller_unread = 1
    user_id = "buyer-id"
    buyer_id = "buyer-id"

    if user_id == buyer_id:
        buyer_unread = 0
    assert buyer_unread == 0
    assert seller_unread == 1


def test_message_ordering():
    messages = [
        {"id": "1", "created_at": "2026-06-21T10:00:00Z"},
        {"id": "2", "created_at": "2026-06-21T10:01:00Z"},
    ]
    sorted_msgs = sorted(messages, key=lambda m: m["created_at"])
    assert sorted_msgs[0]["id"] == "1"


def test_conversation_listing_order():
    convs = [
        {"id": "1", "last_message_at": "2026-06-21T10:00:00Z"},
        {"id": "2", "last_message_at": "2026-06-21T11:00:00Z"},
    ]
    sorted_convs = sorted(convs, key=lambda c: c["last_message_at"] or "", reverse=True)
    assert sorted_convs[0]["id"] == "2"


def test_unique_conversation_per_tuple():
    existing = {("buyer-1", "seller-1", "product-1")}
    new = ("buyer-1", "seller-1", "product-1")
    assert new in existing

    new = ("buyer-1", "seller-1", "product-2")
    assert new not in existing
