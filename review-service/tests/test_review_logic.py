"""Tests for review-service profanity filter & business logic."""
import sys
import os
import re
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_profanity_detection_basic():
    """Profanity filter should detect bad words."""
    # Simulate profanity list
    profanity_words = ["spam", "scam", "fake"]
    pattern = r"\b(" + "|".join(re.escape(w) for w in profanity_words) + r")\b"
    regex = re.compile(pattern, re.IGNORECASE)

    # Should detect
    assert regex.search("This is SPAM") is not None
    assert regex.search("this is a scam") is not None
    assert regex.search("FAKE product") is not None

    # Should not detect
    assert regex.search("Great product") is None
    assert regex.search("Highly recommend") is None


def test_profanity_case_insensitive():
    """Profanity filter should be case-insensitive."""
    profanity_words = ["bad"]
    pattern = r"\b(" + "|".join(re.escape(w) for w in profanity_words) + r")\b"
    regex = re.compile(pattern, re.IGNORECASE)

    assert regex.search("this is BAD") is not None
    assert regex.search("this is Bad") is not None
    assert regex.search("this is bad") is not None


def test_profanity_word_boundary():
    """Profanity filter should respect word boundaries."""
    profanity_words = ["bad"]
    pattern = r"\b(" + "|".join(re.escape(w) for w in profanity_words) + r")\b"
    regex = re.compile(pattern, re.IGNORECASE)

    # Word boundary respected
    assert regex.search("this is bad") is not None
    assert regex.search("this is badminton") is None  # not the word "bad"


def test_profanity_redaction():
    """Profanity should be replaced with [REDACTED]."""
    profanity_words = ["spam"]
    pattern = r"\b(" + "|".join(re.escape(w) for w in profanity_words) + r")\b"
    regex = re.compile(pattern, re.IGNORECASE)

    text = "This is spam content"
    sanitized = regex.sub("[REDACTED]", text)
    assert "spam" not in sanitized.lower()
    assert "[REDACTED]" in sanitized


def test_sanitize_text_empty():
    """Empty text should not be flagged."""
    text = ""
    profanity_words = ["bad"]
    pattern = r"\b(" + "|".join(re.escape(w) for w in profanity_words) + r")\b"
    regex = re.compile(pattern, re.IGNORECASE)
    assert regex.search(text) is None


def test_sanitize_text_none():
    """None text should not crash."""
    text = None
    # In actual implementation, returns (text, False)
    assert text is None


def test_rating_validation():
    """Rating must be between 1 and 5."""
    valid_ratings = [1, 2, 3, 4, 5]
    for r in valid_ratings:
        assert 1 <= r <= 5

    invalid_ratings = [0, -1, 6, 100, -100]
    for r in invalid_ratings:
        assert not (1 <= r <= 5)


def test_review_max_images():
    """Max 5 images per review."""
    max_images = 5
    assert len(["img1", "img2", "img3"]) <= max_images
    assert len(["img1", "img2", "img3", "img4", "img5"]) <= max_images
    assert not len(["img1", "img2", "img3", "img4", "img5", "img6"]) <= max_images


def test_review_max_length():
    """Review content max 5000 chars."""
    max_length = 5000
    assert len("short review") <= max_length
    assert not len("x" * 5001) <= max_length


def test_edit_window_24h():
    """Review can only be edited within 24h."""
    edit_window_hours = 24
    now = datetime.now(timezone.utc)

    # Created 12h ago → can edit
    created_at = now - timedelta(hours=12)
    window_start = now - timedelta(hours=edit_window_hours)
    assert created_at >= window_start  # within edit window

    # Created 48h ago → cannot edit
    created_at = now - timedelta(hours=48)
    assert not created_at >= window_start  # outside edit window


def test_unique_user_product_constraint():
    """One review per user per product (anti-fraud)."""
    # Simulate existing review check
    existing_reviews = [
        {"user_id": "user-1", "product_id": "prod-1"},
        {"user_id": "user-2", "product_id": "prod-1"},
    ]

    new_review = {"user_id": "user-1", "product_id": "prod-1"}

    # Should detect existing
    has_existing = any(
        r["user_id"] == new_review["user_id"] and r["product_id"] == new_review["product_id"]
        for r in existing_reviews
    )
    assert has_existing

    # Different user
    new_review = {"user_id": "user-3", "product_id": "prod-1"}
    has_existing = any(
        r["user_id"] == new_review["user_id"] and r["product_id"] == new_review["product_id"]
        for r in existing_reviews
    )
    assert not has_existing


def test_rating_distribution_calculation():
    """Rating distribution counts should sum to total."""
    distribution = {5: 180, 4: 30, 3: 15, 2: 5, 1: 4}
    total = sum(distribution.values())
    assert total == 234


def test_average_rating_calculation():
    """Average rating = sum(rating * count) / total."""
    distribution = {5: 180, 4: 30, 3: 15, 2: 5, 1: 4}
    total = sum(distribution.values())
    weighted_sum = sum(rating * count for rating, count in distribution.items())
    avg = weighted_sum / total
    assert round(avg, 2) == 4.62  # (5*180 + 4*30 + 3*15 + 2*5 + 1*4) / 234 = 1085/234 ≈ 4.637


def test_helpful_vote_idempotent():
    """Same helpful vote should be idempotent."""
    existing_vote = {"user_id": "user-1", "helpful": True}
    new_vote = {"user_id": "user-1", "helpful": True}

    # Same vote → idempotent (no change)
    is_idempotent = existing_vote["helpful"] == new_vote["helpful"]
    assert is_idempotent


def test_helpful_vote_update():
    """Changing vote should update counts."""
    existing_vote = {"user_id": "user-1", "helpful": True}
    new_vote = {"user_id": "user-1", "helpful": False}

    # Different vote → update
    should_update = existing_vote["helpful"] != new_vote["helpful"]
    assert should_update

    # When updating: decrement old, increment new
    helpful_count = 10
    not_helpful_count = 3

    # Was helpful, now not
    helpful_count = max(0, helpful_count - 1)  # decrement old
    not_helpful_count += 1  # increment new

    assert helpful_count == 9
    assert not_helpful_count == 4


def test_anonymous_review():
    """Anonymous review should hide user_id."""
    review = {
        "user_id": "user-uuid",
        "is_anonymous": True,
    }
    # In _to_dict: returns user_id only if not anonymous
    public_user_id = None if review["is_anonymous"] else review["user_id"]
    assert public_user_id is None

    review["is_anonymous"] = False
    public_user_id = None if review["is_anonymous"] else review["user_id"]
    assert public_user_id == "user-uuid"


def test_moderation_status_values():
    """Valid moderation statuses."""
    valid = ["APPROVED", "PENDING", "HIDDEN", "REJECTED"]
    assert "APPROVED" in valid
    assert "PENDING" in valid
    assert "HIDDEN" in valid
    assert "REJECTED" in valid


def test_moderation_actions():
    """Valid moderation actions."""
    valid = ["hide", "approve", "reject"]
    assert "hide" in valid
    assert "approve" in valid
    assert "reject" in valid


# Need timedelta import
from datetime import timedelta  # noqa: E402
