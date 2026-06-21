"""Auth & user business logic."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MFARequiredError,
    NotFoundError,
    SecurityError,
    ValidationError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_mfa_secret,
    generate_mfa_uri,
    generate_token,
    hash_password,
    is_password_strong,
    verify_mfa,
    verify_password,
)
from app.models.user import User, UserRole
from app.repositories.user_repository import (
    AuditRepository,
    PasswordResetRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.schemas.user import (
    MFASetup,
    MFAVerify,
    PasswordChange,
    PasswordReset,
    PasswordResetRequest,
    TokenRefresh,
    TokenResponse,
    UserLogin,
    UserPublic,
    UserRegister,
    UserUpdate,
)
from app.services.kafka_publisher import audit_publisher

logger = logging.getLogger("auth_service.auth")


class AuthService:
    """Authentication & user management service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)
        self.token_repo = RefreshTokenRepository(db)
        self.reset_repo = PasswordResetRepository(db)
        self.audit_repo = AuditRepository(db)

    async def register(
        self,
        data: UserRegister,
        ip: str,
        user_agent: str,
        correlation_id: str,
    ) -> TokenResponse:
        """Register new user."""
        # Validate password strength
        ok, issues = is_password_strong(data.password)
        if not ok:
            raise ValidationError("weak password", {"issues": issues})

        # Check email availability
        existing = await self.user_repo.get_by_email(data.email)
        if existing is not None:
            # Don't reveal email exists — return conflict anyway for UX
            raise ConflictError("email already registered")

        # Hash password
        password_hash = hash_password(data.password)

        # Create user
        user = await self.user_repo.create({
            "email": data.email.lower().strip(),
            "email_lower": data.email.lower().strip(),
            "password_hash": password_hash,
            "full_name": data.full_name,
            "phone": data.phone,
            "role": UserRole(data.role),
        })

        # Generate tokens
        access_token, access_jti = create_access_token(
            str(user.id),
            [user.role.value],
            self._permissions_for_role(user.role),
        )
        refresh_token, refresh_jti = create_refresh_token(str(user.id))
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        await self.token_repo.create(
            user_id=user.id,
            jti=refresh_jti,
            token=refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )

        # Audit log
        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user.id,
            "actor_role": user.role.value,
            "actor_ip": ip,
            "action": "user.register",
            "resource_type": "user",
            "resource_id": str(user.id),
            "before": None,
            "after": {"id": str(user.id), "email": user.email, "role": user.role.value},
            "correlation_id": correlation_id,
        })

        # Publish event (async, best-effort)
        await audit_publisher.publish(
            action="user.register",
            actor={"user_id": str(user.id), "role": user.role.value, "ip": ip},
            resource={
                "type": "user",
                "id": str(user.id),
                "after": {"email": user.email, "role": user.role.value},
            },
            correlation_id=correlation_id,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserPublic.model_validate(user),
        )

    async def login(
        self,
        data: UserLogin,
        ip: str,
        user_agent: str,
        correlation_id: str,
    ) -> TokenResponse | dict[str, Any]:
        """Login user. Returns token response OR MFA challenge dict."""
        user = await self.user_repo.get_by_email(data.email)
        if user is None:
            # Constant-time fake verify untuk prevent user enumeration via timing
            verify_password(data.password, "$argon2id$v=19$m=65536,t=3,p=4$xxx")
            raise AuthenticationError("invalid credentials")

        # Check account status
        if user.is_banned:
            raise AuthenticationError("account banned")
        if user.is_locked:
            if user.locked_until and user.locked_until > datetime.now(timezone.utc):
                raise AccountLockedError(
                    "account locked",
                    {"locked_until": user.locked_until.isoformat()},
                )
            # Lock expired, unlock
            await self.user_repo.unlock_account(user.id)
            user = await self.user_repo.get_by_id(user.id)
            if user is None:
                raise AuthenticationError("invalid credentials")

        # Verify password
        if not verify_password(data.password, user.password_hash):
            attempts = await self.user_repo.increment_failed_login(user.id)
            if attempts >= settings.MAX_LOGIN_ATTEMPTS:
                logger.warning(
                    "account locked due to failed attempts",
                    extra={"user_id": str(user.id), "attempts": attempts},
                )
            raise AuthenticationError("invalid credentials")

        # MFA check
        if user.mfa_enabled:
            if data.mfa_code is None:
                # Issue MFA token (short-lived, just to identify this session)
                mfa_token = generate_token(32)
                # In production: store in Redis with TTL 5min
                raise MFARequiredError(
                    "mfa code required",
                    {"mfa_token": mfa_token, "email": user.email},
                )
            if not user.mfa_secret:
                raise AuthenticationError("mfa not configured")
            if not verify_mfa(user.mfa_secret, data.mfa_code):
                raise AuthenticationError("invalid mfa code")

        # Reset failed attempts
        await self.user_repo.reset_failed_login(user.id)
        await self.user_repo.update(user.id, {
            "last_login_at": datetime.now(timezone.utc),
            "last_login_ip": ip,
        })

        # Generate tokens
        access_token, _ = create_access_token(
            str(user.id),
            [user.role.value],
            self._permissions_for_role(user.role),
        )
        refresh_token, refresh_jti = create_refresh_token(str(user.id))
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        await self.token_repo.create(
            user_id=user.id,
            jti=refresh_jti,
            token=refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )

        # Audit
        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user.id,
            "actor_role": user.role.value,
            "actor_ip": ip,
            "action": "user.login",
            "resource_type": "user",
            "resource_id": str(user.id),
            "before": None,
            "after": None,
            "correlation_id": correlation_id,
        })

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserPublic.model_validate(user),
        )

    async def refresh(self, data: TokenRefresh, ip: str, correlation_id: str) -> TokenResponse:
        """Rotate refresh token: revoke old, issue new pair."""
        try:
            payload = decode_token(data.refresh_token)
        except Exception as e:
            raise AuthenticationError(f"invalid refresh token: {e}") from e

        if payload.get("type") != "refresh":
            raise AuthenticationError("not a refresh token")

        user_id = UUID(payload["sub"])
        jti = payload["jti"]

        # Verify token exists & not revoked (rotation detection)
        rt = await self.token_repo.verify(data.refresh_token, jti)
        if rt is None:
            # Possible token reuse attack — revoke ALL user tokens
            await self.token_repo.revoke_all_for_user(user_id)
            logger.warning(
                "refresh token reuse detected, all tokens revoked",
                extra={"user_id": str(user_id), "jti": jti},
            )
            raise AuthenticationError("refresh token reuse detected, all sessions revoked")

        user = await self.user_repo.get_by_id(user_id)
        if user is None or not user.is_active or user.is_banned:
            raise AuthenticationError("user account invalid")

        # Revoke old refresh token (rotation)
        await self.token_repo.revoke(jti)

        # Issue new tokens
        access_token, _ = create_access_token(
            str(user.id),
            [user.role.value],
            self._permissions_for_role(user.role),
        )
        new_refresh, new_jti = create_refresh_token(str(user.id))
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        await self.token_repo.create(
            user_id=user.id,
            jti=new_jti,
            token=new_refresh,
            expires_at=expires_at,
            user_agent=None,
            ip=ip,
        )

        # Audit
        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user.id,
            "actor_role": user.role.value,
            "actor_ip": ip,
            "action": "token.refresh",
            "resource_type": "refresh_token",
            "resource_id": jti,
            "before": None,
            "after": {"new_jti": new_jti},
            "correlation_id": correlation_id,
        })

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserPublic.model_validate(user),
        )

    async def logout(self, user_id: UUID, jti: str, ip: str, correlation_id: str) -> None:
        """Logout: revoke refresh token + blacklist access JTI."""
        await self.token_repo.revoke_all_for_user(user_id)
        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user_id,
            "actor_ip": ip,
            "action": "user.logout",
            "resource_type": "user",
            "resource_id": str(user_id),
            "correlation_id": correlation_id,
        })

    async def get_me(self, user_id: UUID) -> UserPublic:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")
        return UserPublic.model_validate(user)

    async def update_me(
        self,
        user_id: UUID,
        data: UserUpdate,
        ip: str,
        correlation_id: str,
    ) -> UserPublic:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")

        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return UserPublic.model_validate(user)

        before = {
            "full_name": user.full_name,
            "phone": user.phone,
        }
        updated = await self.user_repo.update(user_id, updates)
        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user_id,
            "actor_ip": ip,
            "action": "user.update",
            "resource_type": "user",
            "resource_id": str(user_id),
            "before": before,
            "after": updates,
            "correlation_id": correlation_id,
        })
        return UserPublic.model_validate(updated)

    async def change_password(
        self,
        user_id: UUID,
        data: PasswordChange,
        ip: str,
        correlation_id: str,
    ) -> None:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")

        if not verify_password(data.current_password, user.password_hash):
            raise AuthenticationError("current password incorrect")

        ok, issues = is_password_strong(data.new_password)
        if not ok:
            raise ValidationError("weak password", {"issues": issues})

        if data.current_password == data.new_password:
            raise ValidationError("new password must be different from current")

        new_hash = hash_password(data.new_password)
        await self.user_repo.update(user_id, {
            "password_hash": new_hash,
            "password_changed_at": datetime.now(timezone.utc),
        })

        # Revoke all sessions (force re-login)
        await self.token_repo.revoke_all_for_user(user_id)

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user_id,
            "actor_ip": ip,
            "action": "user.password_change",
            "resource_type": "user",
            "resource_id": str(user_id),
            "correlation_id": correlation_id,
        })

    async def request_password_reset(
        self,
        data: PasswordResetRequest,
        ip: str,
        correlation_id: str,
    ) -> dict[str, str]:
        """Request password reset. Always return success to prevent email enumeration."""
        user = await self.user_repo.get_by_email(data.email)
        if user is None:
            # Log but don't reveal
            logger.info("password reset requested for unknown email", extra={"email": data.email})
            return {"message": "if email exists, reset link has been sent"}

        token = generate_token(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await self.reset_repo.create(user.id, token, expires_at)

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user.id,
            "actor_ip": ip,
            "action": "user.password_reset_requested",
            "resource_type": "user",
            "resource_id": str(user.id),
            "correlation_id": correlation_id,
        })

        # In production: send email via notification-service
        # For dev: log the token
        logger.info("password reset token generated", extra={"user_id": str(user.id), "token": token})
        return {"message": "if email exists, reset link has been sent"}

    async def reset_password(
        self,
        data: PasswordReset,
        ip: str,
        correlation_id: str,
    ) -> None:
        prt = await self.reset_repo.get_by_token(data.token)
        if prt is None or prt.is_used or prt.expires_at < datetime.now(timezone.utc):
            raise AuthenticationError("invalid or expired reset token")

        ok, issues = is_password_strong(data.new_password)
        if not ok:
            raise ValidationError("weak password", {"issues": issues})

        user = await self.user_repo.get_by_id(prt.user_id)
        if user is None:
            raise NotFoundError("user not found")

        new_hash = hash_password(data.new_password)
        await self.user_repo.update(user.id, {
            "password_hash": new_hash,
            "password_changed_at": datetime.now(timezone.utc),
        })
        await self.reset_repo.mark_used(prt.id)
        await self.token_repo.revoke_all_for_user(user.id)

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user.id,
            "actor_ip": ip,
            "action": "user.password_reset",
            "resource_type": "user",
            "resource_id": str(user.id),
            "correlation_id": correlation_id,
        })

    async def setup_mfa(
        self,
        user_id: UUID,
        data: MFASetup,
        ip: str,
        correlation_id: str,
    ) -> dict[str, str]:
        """Setup MFA: returns secret + otpauth URI for QR code."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")
        if not verify_password(data.password, user.password_hash):
            raise AuthenticationError("password incorrect")
        if user.mfa_enabled:
            raise ConflictError("mfa already enabled")

        secret = generate_mfa_secret()
        uri = generate_mfa_uri(secret, user.email)

        # Store secret temporarily (not yet verified)
        # In production: store in Redis with TTL 10min
        # For simplicity, store on user model with mfa_enabled=False
        await self.user_repo.update(user_id, {"mfa_secret": secret})

        return {"secret": secret, "otpauth_uri": uri}

    async def verify_mfa_setup(
        self,
        user_id: UUID,
        data: MFAVerify,
        ip: str,
        correlation_id: str,
    ) -> dict[str, bool]:
        """Confirm MFA setup by verifying first code."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")
        if user.mfa_enabled:
            raise ConflictError("mfa already enabled")
        if not user.mfa_secret or user.mfa_secret != data.secret:
            raise SecurityError("secret mismatch")

        if not verify_mfa(user.mfa_secret, data.code):
            raise AuthenticationError("invalid mfa code")

        await self.user_repo.update(user_id, {"mfa_enabled": True})

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user_id,
            "actor_ip": ip,
            "action": "user.mfa_enabled",
            "resource_type": "user",
            "resource_id": str(user_id),
            "correlation_id": correlation_id,
        })

        return {"mfa_enabled": True}

    async def disable_mfa(
        self,
        user_id: UUID,
        password: str,
        mfa_code: str,
        ip: str,
        correlation_id: str,
    ) -> None:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")
        if not user.mfa_enabled:
            raise ConflictError("mfa not enabled")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("password incorrect")
        if not verify_mfa(user.mfa_secret, mfa_code):
            raise AuthenticationError("invalid mfa code")

        await self.user_repo.update(user_id, {
            "mfa_enabled": False,
            "mfa_secret": None,
        })
        await self.token_repo.revoke_all_for_user(user_id)

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": user_id,
            "actor_ip": ip,
            "action": "user.mfa_disabled",
            "resource_type": "user",
            "resource_id": str(user_id),
            "correlation_id": correlation_id,
        })

    # ===== Admin operations =====
    async def admin_list_users(
        self,
        admin_id: UUID,
        admin_role: str,
        role: UserRole | None,
        offset: int,
        limit: int,
        ip: str,
        correlation_id: str,
    ) -> tuple[list[UserPublic], int]:
        if admin_role not in ("admin", "superadmin"):
            raise AuthorizationError("admin access required")

        users, total = await self.user_repo.list_users(role, offset, limit)
        return [UserPublic.model_validate(u) for u in users], total

    async def admin_update_role(
        self,
        admin_id: UUID,
        admin_role: str,
        target_user_id: UUID,
        new_role: UserRole,
        ip: str,
        correlation_id: str,
    ) -> UserPublic:
        if admin_role != "superadmin":
            raise AuthorizationError("superadmin access required")
        if new_role == UserRole.SUPERADMIN:
            # Only existing superadmin can promote, and there must always be 1 superadmin
            pass

        user = await self.user_repo.get_by_id(target_user_id)
        if user is None:
            raise NotFoundError("user not found")
        before = {"role": user.role.value}
        updated = await self.user_repo.update(target_user_id, {"role": new_role})

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": admin_id,
            "actor_role": admin_role,
            "actor_ip": ip,
            "action": "admin.role_change",
            "resource_type": "user",
            "resource_id": str(target_user_id),
            "before": before,
            "after": {"role": new_role.value},
            "correlation_id": correlation_id,
        })
        return UserPublic.model_validate(updated)

    async def admin_ban_user(
        self,
        admin_id: UUID,
        admin_role: str,
        target_user_id: UUID,
        is_banned: bool,
        reason: str | None,
        ip: str,
        correlation_id: str,
    ) -> UserPublic:
        if admin_role not in ("admin", "superadmin"):
            raise AuthorizationError("admin access required")

        user = await self.user_repo.get_by_id(target_user_id)
        if user is None:
            raise NotFoundError("user not found")
        if user.role == UserRole.SUPERADMIN and is_banned:
            raise AuthorizationError("cannot ban superadmin")

        before = {"is_banned": user.is_banned}
        updated = await self.user_repo.update(target_user_id, {"is_banned": is_banned})
        if is_banned:
            await self.token_repo.revoke_all_for_user(target_user_id)

        await self.audit_repo.log({
            "timestamp": datetime.now(timezone.utc),
            "actor_user_id": admin_id,
            "actor_role": admin_role,
            "actor_ip": ip,
            "action": "admin.user_ban" if is_banned else "admin.user_unban",
            "resource_type": "user",
            "resource_id": str(target_user_id),
            "before": before,
            "after": {"is_banned": is_banned, "reason": reason},
            "correlation_id": correlation_id,
        })
        return UserPublic.model_validate(updated)

    def _permissions_for_role(self, role: UserRole) -> list[str]:
        """Return permission list for role."""
        permissions = {
            UserRole.BUYER: [
                "product:read", "cart:write", "order:create", "order:read:own",
                "payment:create", "payment:read:own", "review:write",
                "profile:read:own", "profile:write:own",
            ],
            UserRole.SELLER: [
                "product:read", "product:write:own", "cart:write", "order:create",
                "order:read:own_product", "order:read:own", "payment:create",
                "payment:read:own", "withdrawal:request", "withdrawal:read:own",
                "review:write", "profile:read:own", "profile:write:own",
            ],
            UserRole.ADMIN: [
                "product:read", "product:write:all", "order:read:all",
                "payment:read:all", "payment:refund", "user:read", "user:ban",
                "audit:read", "config:read",
            ],
            UserRole.SUPERADMIN: [
                "product:read", "product:write:all", "order:read:all",
                "payment:read:all", "payment:refund", "user:read", "user:write",
                "user:ban", "user:role_change", "audit:read", "config:write",
            ],
        }
        return permissions.get(role, [])
