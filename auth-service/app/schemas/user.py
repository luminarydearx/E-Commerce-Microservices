"""Pydantic schemas for auth-service."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ===== Auth =====
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    role: Literal["buyer", "seller"] = "buyer"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^\+?[1-9]\d{6,14}$", v):
            raise ValueError("phone must be in E.164 format")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=6)


class TokenRefresh(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class MFASetup(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MFAVerify(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    secret: str = Field(min_length=16, max_length=64)


class MFAVerifyLogin(BaseModel):
    email: EmailStr
    mfa_code: str = Field(min_length=6, max_length=6)
    mfa_token: str = Field(min_length=10, max_length=256)


# ===== Responses =====
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: "UserPublic"


class UserPublic(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    phone: str | None
    role: str
    is_email_verified: bool
    is_phone_verified: bool
    mfa_enabled: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^\+?[1-9]\d{6,14}$", v):
            raise ValueError("phone must be in E.164 format")
        return v


class AdminUserList(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    is_active: bool
    is_banned: bool
    is_locked: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    role: Literal["buyer", "seller", "admin", "superadmin"]


class BanUpdate(BaseModel):
    is_banned: bool
    reason: str | None = Field(default=None, max_length=500)


TokenResponse.model_rebuild()
