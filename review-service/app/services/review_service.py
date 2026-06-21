"""Review business logic with anti-fraud, moderation, helpful votes."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey

from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import (
    ConflictError, ForbiddenError, NotFoundError, ValidationError,
)

logger = logging.getLogger("review_service.service")


# ===== Models =====

class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = {"schema": "review"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    order_item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    seller_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    helpful_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    not_helpful_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    seller_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    moderation_status: Mapped[str] = mapped_column(String(20), default="APPROVED", nullable=False)
    moderation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class HelpfulVote(Base):
    __tablename__ = "helpful_votes"
    __table_args__ = {"schema": "review"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    review_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("review.reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    helpful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = ({"schema": "review"}, {"unique_constraint": "uq_helpful_review_user"})


# ===== Service =====

PROFANITY_REGEX = None


def get_profanity_regex():
    global PROFANITY_REGEX
    if PROFANITY_REGEX is None and settings.PROFANITY_ENABLED:
        words = settings.PROFANITY_WORDS or []
        if words:
            pattern = r"\b(" + "|".join(re.escape(w) for w in words) + r")\b"
            PROFANITY_REGEX = re.compile(pattern, re.IGNORECASE)
    return PROFANITY_REGEX


def sanitize_text(text: str) -> tuple[str, bool]:
    """Return (sanitized_text, had_profanity)."""
    if not text:
        return text, False
    regex = get_profanity_regex()
    if regex is None:
        return text, False
    if regex.search(text):
        sanitized = regex.sub("[REDACTED]", text)
        return sanitized, True
    return text, False


class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_review(self, user_id: str, data, ip: str, correlation_id: str) -> dict:
        uid = UUID(user_id)
        product_id = UUID(data.product_id)
        order_item_id = UUID(data.order_item_id)

        # Check: user must have purchased this product (anti-fraud)
        # In production: query order-service via gRPC to verify
        # For now: trust the order_item_id, but check unique constraint

        # Check existing review from same user for same product
        existing = await self.db.execute(
            select(Review).where(
                Review.user_id == uid,
                Review.product_id == product_id,
                Review.is_deleted == False,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError("you have already reviewed this product")

        # Validate rating
        if not 1 <= data.rating <= 5:
            raise ValidationError("rating must be between 1 and 5")

        # Sanitize content for profanity
        title, title_flagged = sanitize_text(data.title)
        content, content_flagged = sanitize_text(data.content)

        moderation_status = "APPROVED"
        if settings.REVIEW_MODERATION_ENABLED and (title_flagged or content_flagged):
            moderation_status = "PENDING"  # require manual review

        # Determine seller_id (in production: fetch from catalog-service)
        seller_id = UUID("00000000-0000-0000-0000-000000000000")  # placeholder

        review = Review(
            id=uuid4(),
            product_id=product_id,
            order_item_id=order_item_id,
            user_id=uid,
            seller_id=seller_id,
            rating=data.rating,
            title=title,
            content=content,
            images=data.images if data.images else None,
            is_anonymous=data.is_anonymous,
            moderation_status=moderation_status,
        )
        self.db.add(review)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(review)

        logger.info("review created", extra={
            "review_id": str(review.id), "product_id": str(product_id),
            "user_id": user_id, "rating": data.rating,
        })

        return self._to_dict(review)

    async def list_product_reviews(self, product_id: str, page: int, size: int,
                                    sort: str, rating_filter: int | None,
                                    with_images: bool) -> dict:
        pid = UUID(product_id)
        if size > 100:
            size = 100

        stmt = select(Review).where(
            Review.product_id == pid,
            Review.is_deleted == False,
            Review.is_hidden == False,
            Review.moderation_status == "APPROVED",
        )
        count_stmt = select(func.count(Review.id)).where(
            Review.product_id == pid,
            Review.is_deleted == False,
            Review.is_hidden == False,
            Review.moderation_status == "APPROVED",
        )

        if rating_filter:
            stmt = stmt.where(Review.rating == rating_filter)
            count_stmt = count_stmt.where(Review.rating == rating_filter)
        if with_images:
            stmt = stmt.where(Review.images.isnot(None))

        if sort == "helpful":
            stmt = stmt.order_by(desc(Review.helpful_count), desc(Review.created_at))
        elif sort == "highest":
            stmt = stmt.order_by(desc(Review.rating), desc(Review.created_at))
        elif sort == "lowest":
            stmt = stmt.order_by(Review.rating.asc(), desc(Review.created_at))
        else:  # recent
            stmt = stmt.order_by(desc(Review.created_at))

        stmt = stmt.offset(page * size).limit(size)
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        return {
            "data": [self._to_dict(r) for r in reviews],
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_rating_summary(self, product_id: str) -> dict:
        pid = UUID(product_id)
        # Get rating distribution & average
        result = await self.db.execute(
            select(
                Review.rating,
                func.count(Review.id).label("count"),
            ).where(
                Review.product_id == pid,
                Review.is_deleted == False,
                Review.is_hidden == False,
                Review.moderation_status == "APPROVED",
            ).group_by(Review.rating)
        )
        distribution = {row.rating: row.count for row in result}

        # Calculate average
        avg_result = await self.db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.product_id == pid,
                Review.is_deleted == False,
                Review.is_hidden == False,
                Review.moderation_status == "APPROVED",
            )
        )
        avg_row = avg_result.first()
        average = float(avg_row[0]) if avg_row[0] else 0.0
        total_count = int(avg_row[1]) if avg_row[1] else 0

        return {
            "product_id": product_id,
            "average_rating": round(average, 2),
            "total_reviews": total_count,
            "distribution": {
                "5": distribution.get(5, 0),
                "4": distribution.get(4, 0),
                "3": distribution.get(3, 0),
                "2": distribution.get(2, 0),
                "1": distribution.get(1, 0),
            },
        }

    async def get_review(self, review_id: str) -> dict:
        rid = UUID(review_id)
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review or review.is_deleted:
            raise NotFoundError("review not found")
        return self._to_dict(review)

    async def update_review(self, review_id: str, user_id: str, data) -> dict:
        rid = UUID(review_id)
        uid = UUID(user_id)
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review or review.is_deleted:
            raise NotFoundError("review not found")
        if review.user_id != uid:
            raise ForbiddenError("cannot edit another user's review")

        # Edit window check
        edit_window = datetime.now(timezone.utc) - timedelta(hours=settings.REVIEW_EDIT_WINDOW_HOURS)
        if review.created_at < edit_window:
            raise ValidationError(f"review can only be edited within {settings.REVIEW_EDIT_WINDOW_HOURS} hours")

        title, _ = sanitize_text(data.title)
        content, _ = sanitize_text(data.content)

        review.rating = data.rating
        review.title = title
        review.content = content
        review.images = data.images if data.images else None
        review.is_edited = True
        review.updated_at = datetime.now(timezone.utc)
        review.version += 1

        await self.db.commit()
        await self.db.refresh(review)
        return self._to_dict(review)

    async def delete_review(self, review_id: str, user_id: str) -> None:
        rid = UUID(review_id)
        uid = UUID(user_id)
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review:
            raise NotFoundError("review not found")
        if review.user_id != uid:
            raise ForbiddenError("cannot delete another user's review")

        # Soft delete
        review.is_deleted = True
        review.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def vote_helpful(self, review_id: str, user_id: str, helpful: bool) -> dict:
        rid = UUID(review_id)
        uid = UUID(user_id)

        # Check review exists
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review or review.is_deleted:
            raise NotFoundError("review not found")

        # Check existing vote
        existing = await self.db.execute(
            select(HelpfulVote).where(
                HelpfulVote.review_id == rid,
                HelpfulVote.user_id == uid,
            )
        )
        existing_vote = existing.scalar_one_or_none()

        if existing_vote:
            if existing_vote.helpful == helpful:
                # Idempotent: same vote
                return {"helpful_count": review.helpful_count, "not_helpful_count": review.not_helpful_count}
            # Update vote
            if existing_vote.helpful:
                review.helpful_count = max(0, review.helpful_count - 1)
            else:
                review.not_helpful_count = max(0, review.not_helpful_count - 1)
            existing_vote.helpful = helpful
        else:
            new_vote = HelpfulVote(
                id=uuid4(),
                review_id=rid,
                user_id=uid,
                helpful=helpful,
            )
            self.db.add(new_vote)

        if helpful:
            review.helpful_count += 1
        else:
            review.not_helpful_count += 1

        await self.db.commit()
        return {"helpful_count": review.helpful_count, "not_helpful_count": review.not_helpful_count}

    async def seller_response(self, review_id: str, seller_id: str, content: str) -> dict:
        rid = UUID(review_id)
        sid = UUID(seller_id)
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review or review.is_deleted:
            raise NotFoundError("review not found")

        # Verify seller owns the product
        if review.seller_id != sid:
            raise ForbiddenError("not the seller of this product's review")

        sanitized, _ = sanitize_text(content)
        review.seller_response = sanitized
        review.seller_response_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(review)
        return self._to_dict(review)

    async def list_user_reviews(self, user_id: str, page: int, size: int) -> dict:
        uid = UUID(user_id)
        stmt = select(Review).where(
            Review.user_id == uid,
            Review.is_deleted == False,
        ).order_by(desc(Review.created_at)).offset(page * size).limit(size)
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()
        count_result = await self.db.execute(
            select(func.count(Review.id)).where(
                Review.user_id == uid, Review.is_deleted == False
            )
        )
        total = count_result.scalar() or 0
        return {"data": [self._to_dict(r) for r in reviews], "total": total, "page": page, "size": size}

    async def moderate_review(self, review_id: str, action: str, reason: str, admin_id: str) -> dict:
        rid = UUID(review_id)
        result = await self.db.execute(select(Review).where(Review.id == rid))
        review = result.scalar_one_or_none()
        if not review:
            raise NotFoundError("review not found")

        if action == "hide":
            review.is_hidden = True
            review.moderation_status = "HIDDEN"
        elif action == "approve":
            review.is_hidden = False
            review.moderation_status = "APPROVED"
        elif action == "reject":
            review.is_hidden = True
            review.moderation_status = "REJECTED"
        else:
            raise ValidationError(f"invalid action: {action}")

        review.moderation_reason = reason
        await self.db.commit()
        await self.db.refresh(review)
        return self._to_dict(review)

    def _to_dict(self, review: Review) -> dict:
        return {
            "id": str(review.id),
            "product_id": str(review.product_id),
            "order_item_id": str(review.order_item_id),
            "user_id": str(review.user_id) if not review.is_anonymous else None,
            "rating": review.rating,
            "title": review.title,
            "content": review.content,
            "images": review.images or [],
            "is_anonymous": review.is_anonymous,
            "is_edited": review.is_edited,
            "helpful_count": review.helpful_count,
            "not_helpful_count": review.not_helpful_count,
            "seller_response": review.seller_response,
            "seller_response_at": review.seller_response_at.isoformat() if review.seller_response_at else None,
            "moderation_status": review.moderation_status,
            "created_at": review.created_at.isoformat(),
            "updated_at": review.updated_at.isoformat(),
        }
