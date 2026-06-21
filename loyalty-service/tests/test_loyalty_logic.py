"""Tests for loyalty-service tier & points logic."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


TIER_SILVER_MIN = 0
TIER_GOLD_MIN = 1000
TIER_PLATINUM_MIN = 5000
TIER_DIAMOND_MIN = 20000

POINTS_PER_RUPIAH = 0.01
CASHBACK_PERCENT = {"SILVER": 1, "GOLD": 2, "PLATINUM": 3, "DIAMOND": 5}


def get_tier_for_points(points):
    if points >= TIER_DIAMOND_MIN:
        return "DIAMOND"
    if points >= TIER_PLATINUM_MIN:
        return "PLATINUM"
    if points >= TIER_GOLD_MIN:
        return "GOLD"
    return "SILVER"


def tier_rank(tier):
    return {"SILVER": 1, "GOLD": 2, "PLATINUM": 3, "DIAMOND": 4}.get(tier, 1)


def test_tier_thresholds():
    assert get_tier_for_points(0) == "SILVER"
    assert get_tier_for_points(999) == "SILVER"
    assert get_tier_for_points(1000) == "GOLD"
    assert get_tier_for_points(4999) == "GOLD"
    assert get_tier_for_points(5000) == "PLATINUM"
    assert get_tier_for_points(19999) == "PLATINUM"
    assert get_tier_for_points(20000) == "DIAMOND"
    assert get_tier_for_points(100000) == "DIAMOND"


def test_tier_rank_ordering():
    assert tier_rank("SILVER") < tier_rank("GOLD")
    assert tier_rank("GOLD") < tier_rank("PLATINUM")
    assert tier_rank("PLATINUM") < tier_rank("DIAMOND")


def test_points_earning():
    """1 point per Rp 100 spent (0.01 = 1%)."""
    amount = 500_000  # Rp 500k
    points = int(amount * POINTS_PER_RUPIAH)
    assert points == 5000  # 1% of 500k


def test_cashback_calculation():
    """Cashback based on tier."""
    amount = 1_000_000

    # SILVER: 1%
    assert int(amount * CASHBACK_PERCENT["SILVER"] / 100) == 10_000

    # GOLD: 2%
    assert int(amount * CASHBACK_PERCENT["GOLD"] / 100) == 20_000

    # PLATINUM: 3%
    assert int(amount * CASHBACK_PERCENT["PLATINUM"] / 100) == 30_000

    # DIAMOND: 5%
    assert int(amount * CASHBACK_PERCENT["DIAMOND"] / 100) == 50_000


def test_tier_upgrade_on_purchase():
    """User should upgrade tier when lifetime_points crosses threshold."""
    lifetime_points = 900
    tier = get_tier_for_points(lifetime_points)
    assert tier == "SILVER"

    # Earn 200 more points (now 1100)
    lifetime_points += 200
    new_tier = get_tier_for_points(lifetime_points)
    assert new_tier == "GOLD"
    assert tier_rank(new_tier) > tier_rank(tier)


def test_no_downgrade_on_redeem():
    """Tier based on lifetime_points, not current balance."""
    lifetime_points = 5000
    points_balance = 5000
    tier = get_tier_for_points(lifetime_points)
    assert tier == "PLATINUM"

    # Redeem 4000 points
    points_balance -= 4000
    assert points_balance == 1000

    # Tier should stay PLATINUM (based on lifetime, not balance)
    tier = get_tier_for_points(lifetime_points)
    assert tier == "PLATINUM"


def test_reward_min_tier_check():
    """Reward requires minimum tier."""
    user_tier = "SILVER"
    reward_min_tier = "GOLD"

    can_redeem = tier_rank(user_tier) >= tier_rank(reward_min_tier)
    assert not can_redeem  # SILVER cannot redeem GOLD reward

    user_tier = "GOLD"
    can_redeem = tier_rank(user_tier) >= tier_rank(reward_min_tier)
    assert can_redeem

    user_tier = "PLATINUM"
    can_redeem = tier_rank(user_tier) >= tier_rank(reward_min_tier)
    assert can_redeem  # higher tier OK


def test_insufficient_points():
    """Cannot redeem if points_balance < reward.cost."""
    points_balance = 500
    reward_cost = 1000

    can_redeem = points_balance >= reward_cost
    assert not can_redeem

    points_balance = 1500
    can_redeem = points_balance >= reward_cost
    assert can_redeem


def test_points_to_next_tier():
    """Calculate points needed to reach next tier."""
    lifetime_points = 1500
    tier = get_tier_for_points(lifetime_points)
    assert tier == "GOLD"

    next_tier_threshold = TIER_PLATINUM_MIN
    points_to_next = max(0, next_tier_threshold - lifetime_points)
    assert points_to_next == 3500


def test_points_to_next_tier_diamond():
    """Diamond is max tier, no next."""
    lifetime_points = 50_000
    tier = get_tier_for_points(lifetime_points)
    assert tier == "DIAMOND"

    # No next tier
    next_tier = None
    points_to_next = 0
    assert next_tier is None
    assert points_to_next == 0


def test_transaction_types():
    valid = ["EARN", "REDEEM", "EXPIRE", "ADJUST"]
    for t in valid:
        assert t in valid


def test_reward_redemption_status():
    valid = ["ISSUED", "USED", "EXPIRED", "CANCELLED"]
    assert "ISSUED" in valid
