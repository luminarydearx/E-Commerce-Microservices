"""User repository with parameterized queries (anti SQL injection)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import constant_time_compare
from app.models.user import AuditLog, PasswordResetToken, RefreshToken, User, UserRole


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict[str, Any]) -> User:
        try:
            user = User(**data)
            self.db.add(user)
            await self.db.flush()
            await self.db.refresh(user)
            return user
        except IntegrityError as e:
            await self.db.rollback()
            if "email" in str(e).lower():
                raise ConflictError("email already registered")
            raise ConflictError("duplicate entry")

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        email_lower = email.lower().strip()
        result = await self.db.execute(
            select(User).where(User.email_lower == email_lower)
        )
        return result.scalar_one_or_none()

    async def update(self, user_id: UUID, data: dict[str, Any]) -> User:
        # Optimistic locking via version column
        current = await self.get_by_id(user_id)
        if current is None:
            raise NotFoundError("user not found")

        version = current.version
        result = await self.db.execute(
            update(User)
            .where(User.id == user_id, User.version == version)
            .values(**data, version=version + 1)
            .returning(User)
        )
        updated = result.scalar_one_or_none()
        if updated is None:
            raise ConflictError("concurrent update detected, please retry")
        return updated

    async def increment_failed_login(self, user_id: UUID) -> int:
        user = await self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user not found")
        attempts = user.failed_login_attempts + 1
        updates: dict[str, Any] = {"failed_login_attempts": attempts}
        if attempts >= 5:  # MAX_LOGIN_ATTEMPTS
            updates["is_locked"] = True
            updates["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=30)
        await self.update(user_id, updates)
        return attempts

    async def reset_failed_login(self, user_id: UUID) -> None:
        await self.update(user_id, {
            "failed_login_attempts": 0,
            "is_locked": False,
            "locked_until": None,
            "last_login_at": datetime.now(timezone.utc),
        })

    async def lock_account(self, user_id: UUID, until: datetime) -> None:
        await self.update(user_id, {
            "is_locked": True,
            "locked_until": until,
        })

    async def unlock_account(self, user_id: UUID) -> None:
        await self.update(user_id, {
            "is_locked": False,
            "locked_until": None,
            "failed_login_attempts": 0,
        })

    async def list_users(
        self,
        role: UserRole | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        stmt = select(User)
        count_stmt = select(func.count(User.id))
        if role:
            stmt = stmt.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        users = list(result.scalars().all())
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0
        return users, total


class RefreshTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def hash_token(token: str) -> str:
        """SHA256 hash untuk storage (token tidak disimpan plain)."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create(
        self,
        user_id: UUID,
        jti: str,
        token: str,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> RefreshToken:
        rt = RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=self.hash_token(token),
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip,
        )
        self.db.add(rt)
        await self.db.flush()
        return rt

    async def get_by_jti(self, jti: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        return result.scalar_one_or_none()

    async def revoke(self, jti: str) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.jti == jti)
            .values(is_revoked=True)
        )

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        result = await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
            .values(is_revoked=True)
        )
        return result.rowcount or 0

    async def verify(self, token: str, jti: str) -> RefreshToken | None:
        rt = await self.get_by_jti(jti)
        if rt is None:
            return None
        if rt.is_revoked:
            return None
        if rt.expires_at < datetime.now(timezone.utc):
            return None
        if not constant_time_compare(rt.token_hash, self.hash_token(token)):
            return None
        return rt

    async def cleanup_expired(self) -> int:
        """Hapus expired refresh tokens (cron job)."""
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.expires_at < datetime.now(timezone.utc))
        )
        expired = result.scalars().all()
        for rt in expired:
            await self.db.delete(rt)
        return len(expired)


class PasswordResetRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create(self, user_id: UUID, token: str, expires_at: datetime) -> PasswordResetToken:
        prt = PasswordResetToken(
            user_id=user_id,
            token_hash=self.hash_token(token),
            expires_at=expires_at,
        )
        self.db.add(prt)
        await self.db.flush()
        return prt

    async def get_by_token(self, token: str) -> PasswordResetToken | None:
        h = self.hash_token(token)
        result = await self.db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == h)
        )
        return result.scalar_one_or_none()

    async def mark_used(self, token_id: UUID) -> None:
        await self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(is_used=True, used_at=datetime.now(timezone.utc))
        )


class AuditRepository:
    """Local audit log repository (also published to Kafka)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(self, data: dict[str, Any]) -> AuditLog:
        # Serialize before/after to JSON
        before = data.pop("before", None)
        after = data.pop("after", None)
        if before is not None:
            data["before"] = json.dumps(before, default=str)
        if after is not None:
            data["after"] = json.dumps(after, default=str)
        entry = AuditLog(**data)
        self.db.add(entry)
        await self.db.flush()
        return entry
