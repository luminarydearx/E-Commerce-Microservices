"""Unit tests for auth-service security utilities."""
import pytest
from app.core.security import (
    is_password_strong,
    hash_password,
    verify_password,
    constant_time_compare,
    generate_token,
)


class TestPasswordStrength:
    def test_strong_password(self):
        ok, issues = is_password_strong("StrongP@ss123!")
        assert ok is True
        assert issues == []

    def test_short_password(self):
        ok, issues = is_password_strong("Short1!")
        assert ok is False
        assert any("at least" in i for i in issues)

    def test_no_uppercase(self):
        ok, issues = is_password_strong("weakpassword123!")
        assert ok is False
        assert any("uppercase" in i for i in issues)

    def test_no_lowercase(self):
        ok, issues = is_password_strong("WEAKPASSWORD123!")
        assert ok is False
        assert any("lowercase" in i for i in issues)

    def test_no_digit(self):
        ok, issues = is_password_strong("WeakPassword!")
        assert ok is False
        assert any("digit" in i for i in issues)

    def test_no_symbol(self):
        ok, issues = is_password_strong("WeakPassword123")
        assert ok is False
        assert any("special" in i for i in issues)

    def test_common_password(self):
        ok, issues = is_password_strong("Password123!")
        assert ok is False
        assert any("common" in i for i in issues)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        plain = "StrongP@ss123!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("StrongP@ss123!")
        assert verify_password("WrongPassword!", hashed) is False

    def test_hash_is_unique(self):
        h1 = hash_password("StrongP@ss123!")
        h2 = hash_password("StrongP@ss123!")
        assert h1 != h2  # salt makes them different

    def test_short_password_rejected(self):
        with pytest.raises(Exception):
            hash_password("short")


class TestConstantTimeCompare:
    def test_equal_strings(self):
        assert constant_time_compare("abc123", "abc123") is True

    def test_different_strings(self):
        assert constant_time_compare("abc123", "abc124") is False

    def test_different_length(self):
        assert constant_time_compare("abc", "abcd") is False

    def test_empty_strings(self):
        assert constant_time_compare("", "") is True


class TestTokenGeneration:
    def test_token_length(self):
        token = generate_token(32)
        assert len(token) >= 32  # base64 encoding makes it longer

    def test_token_uniqueness(self):
        t1 = generate_token(32)
        t2 = generate_token(32)
        assert t1 != t2
