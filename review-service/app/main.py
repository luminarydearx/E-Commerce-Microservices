"""Review & Rating Service — product reviews, ratings, helpful votes, seller responses."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.logging import setup_logging
from app.core.redis import redis_client
from app.observability.metrics import register_metrics
from app.services.review_service import ReviewService

setup_logging()
logger = logging.getLogger("review_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting review-service")
    register_metrics()
    try:
        await redis_client.ping()
    except Exception as e:
        logger.error("redis ping failed", extra={"error": str(e)})
    yield
    logger.info("shutting down review-service")
    await redis_client.close()
    await engine.dispose()


app = FastAPI(
    title="Review & Rating Service",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "alive", "service": "review-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content=generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


def get_user_id(request: Request) -> str:
    uid = request.headers.get("X-User-Id", "")
    if not uid:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return uid


def get_user_roles(request: Request) -> list[str]:
    roles = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in roles.split(",") if r.strip()]


# ===== Schemas =====

class ReviewCreate(BaseModel):
    product_id: str
    order_item_id: str
    rating: int = Field(ge=1, le=5)
    title: str = Field(max_length=200)
    content: str = Field(max_length=5000)
    images: list[str] = Field(default=[], max_length=5)
    is_anonymous: bool = False

    @field_validator("images")
    @classmethod
    def validate_images(cls, v):
        if len(v) > 5:
            raise ValueError("max 5 images per review")
        return v


class ReviewUpdate(BaseModel):
    rating: int = Field(ge=1, le=5)
    title: str = Field(max_length=200)
    content: str = Field(max_length=5000)
    images: list[str] = Field(default=[], max_length=5)


class SellerResponse(BaseModel):
    content: str = Field(max_length=2000)


class HelpfulVote(BaseModel):
    helpful: bool


# ===== Routes =====

@app.post("/api/v1/reviews")
async def create_review(req: ReviewCreate, request: Request):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        review = await svc.create_review(
            user_id=uid,
            data=req,
            ip=request.client.host if request.client else "",
            correlation_id=request.headers.get("X-Correlation-Id", ""),
        )
        return review


@app.get("/api/v1/products/{product_id}/reviews")
async def list_product_reviews(
    product_id: str,
    request: Request,
    page: int = 0,
    size: int = 20,
    sort: str = "recent",  # recent, helpful, highest, lowest
    rating_filter: int | None = None,
    with_images: bool = False,
):
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.list_product_reviews(
            product_id=product_id, page=page, size=size,
            sort=sort, rating_filter=rating_filter, with_images=with_images,
        )


@app.get("/api/v1/products/{product_id}/rating-summary")
async def get_rating_summary(product_id: str):
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.get_rating_summary(product_id)


@app.get("/api/v1/reviews/{review_id}")
async def get_review(review_id: str):
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.get_review(review_id)


@app.put("/api/v1/reviews/{review_id}")
async def update_review(review_id: str, req: ReviewUpdate, request: Request):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.update_review(review_id, uid, req)


@app.delete("/api/v1/reviews/{review_id}")
async def delete_review(review_id: str, request: Request):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        await svc.delete_review(review_id, uid)
        return JSONResponse(status_code=204, content=None)


@app.post("/api/v1/reviews/{review_id}/helpful")
async def vote_helpful(review_id: str, req: HelpfulVote, request: Request):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.vote_helpful(review_id, uid, req.helpful)


@app.post("/api/v1/reviews/{review_id}/seller-response")
async def seller_respond(review_id: str, req: SellerResponse, request: Request):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    roles = get_user_roles(request)
    if "seller" not in roles and "admin" not in roles:
        return JSONResponse(status_code=403, content={"error": "seller role required"})
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.seller_response(review_id, uid, req.content)


@app.get("/api/v1/users/{user_id}/reviews")
async def list_user_reviews(user_id: str, request: Request, page: int = 0, size: int = 20):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    # Only owner or admin can see user's reviews
    if uid != user_id and "admin" not in get_user_roles(request):
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.list_user_reviews(user_id, page, size)


@app.post("/api/v1/admin/reviews/{review_id}/moderate")
async def moderate_review(review_id: str, request: Request, action: str = "hide", reason: str = ""):
    uid = get_user_id(request)
    if isinstance(uid, JSONResponse):
        return uid
    if "admin" not in get_user_roles(request) and "superadmin" not in get_user_roles(request):
        return JSONResponse(status_code=403, content={"error": "admin required"})
    async with AsyncSessionLocal() as db:
        svc = ReviewService(db)
        return await svc.moderate_review(review_id, action, reason, uid)
