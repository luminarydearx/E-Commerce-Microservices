"""Unit tests for auth-service schemas."""
import pytest
from pydantic import ValidationError

from app.schemas.user import UserRegister, UserLogin, UserUpdate


class TestUserRegister:
    def test_valid_buyer(self):
        user = UserRegister(
            email="user@example.com",
            password="StrongP@ss123!",
            role="buyer",
        )
        assert user.email == "user@example.com"
        assert user.role == "buyer"

    def test_valid_seller(self):
        user = UserRegister(
            email="seller@example.com",
            password="StrongP@ss123!",
            role="seller",
        )
        assert user.role == "seller"

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            UserRegister(
                email="user@example.com",
                password="StrongP@ss123!",
                role="admin",  # cannot self-register as admin
            )

    def test_short_password(self):
        with pytest.raises(ValidationError):
            UserRegister(
                email="user@example.com",
                password="short",
            )

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            UserRegister(
                email="not-an-email",
                password="StrongP@ss123!",
            )

    def test_phone_e164(self):
        user = UserRegister(
            email="user@example.com",
            password="StrongP@ss123!",
            phone="+6281234567890",
        )
        assert user.phone == "+6281234567890"

    def test_phone_invalid(self):
        with pytest.raises(ValidationError):
            UserRegister(
                email="user@example.com",
                password="StrongP@ss123!",
                phone="08123",  # not E.164
            )


class TestUserLogin:
    def test_valid(self):
        login = UserLogin(
            email="user@example.com",
            password="anypassword",
        )
        assert login.email == "user@example.com"

    def test_empty_password(self):
        with pytest.raises(ValidationError):
            UserLogin(email="user@example.com", password="")


class TestUserUpdate:
    def test_partial_update(self):
        update = UserUpdate(full_name="New Name")
        assert update.full_name == "New Name"
        assert update.phone is None

    def test_phone_validation(self):
        with pytest.raises(ValidationError):
            UserUpdate(phone="invalid")
