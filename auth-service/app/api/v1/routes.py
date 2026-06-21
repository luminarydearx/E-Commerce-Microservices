"""API v1 routes untuk auth-service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MFARequiredError,
    NotFoundError,
    ValidationError,
)
from app.models.user import UserRole
from app.schemas.user import (
    AdminUserList,
    BanUpdate,
    MFASetup,
    MFAVerify,
    PasswordChange,
    PasswordReset,
    PasswordResetRequest,
    RoleUpdate,
    TokenRefresh,
    TokenResponse,
    UserLogin,
    UserPublic,
    UserRegister,
    UserUpdate,
)
from app.services.auth_service import AuthService

router = APIRouter()


def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id", "")


def get_user_id(request: Request) -> str:
    uid = request.headers.get("X-User-Id", "")
    if not uid:
        raise AuthenticationError("missing user context")
    return uid


def get_user_roles(request: Request) -> list[str]:
    roles = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in roles.split(",") if r.strip()]


# ===== Auth endpoints =====
@router.post("/auth/register", response_model=TokenResponse, status_code=201)
async def register(
    data: UserRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.register(
        data=data,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
        correlation_id=get_correlation_id(request),
    )


@router.post("/auth/login")
async def login(
    data: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    try:
        return await svc.login(
            data=data,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
            correlation_id=get_correlation_id(request),
        )
    except MFARequiredError as e:
        return e.details  # contains mfa_token


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    data: TokenRefresh,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.refresh(
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = get_user_id(request)
    # JTI is in the access token, but API Gateway doesn't forward it.
    # Use a placeholder — real logout relies on refresh token revocation
    svc = AuthService(db)
    await svc.logout(
        user_id=user_id,
        jti="",
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.post("/auth/forgot-password", status_code=200)
async def forgot_password(
    data: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.request_password_reset(
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.post("/auth/reset-password", status_code=200)
async def reset_password(
    data: PasswordReset,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    await svc.reset_password(
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )
    return {"message": "password has been reset"}


# ===== User profile endpoints =====
@router.get("/users/me", response_model=UserPublic)
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    svc = AuthService(db)
    return await svc.get_me(get_user_id(request))


@router.put("/users/me", response_model=UserPublic)
async def update_me(
    data: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.update_me(
        user_id=get_user_id(request),
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.post("/users/me/change-password", status_code=204)
async def change_password(
    data: PasswordChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    await svc.change_password(
        user_id=get_user_id(request),
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


# ===== MFA endpoints =====
@router.post("/users/me/mfa/setup")
async def mfa_setup(
    data: MFASetup,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.setup_mfa(
        user_id=get_user_id(request),
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.post("/users/me/mfa/verify")
async def mfa_verify(
    data: MFAVerify,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc = AuthService(db)
    return await svc.verify_mfa_setup(
        user_id=get_user_id(request),
        data=data,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


# ===== Admin endpoints =====
@router.get("/admin/users", response_model=list[AdminUserList])
async def admin_list_users(
    request: Request,
    role: UserRole | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        raise AuthorizationError("admin access required")
    svc = AuthService(db)
    users, _ = await svc.admin_list_users(
        admin_id=get_user_id(request),
        admin_role=roles[0],
        role=role,
        offset=offset,
        limit=limit,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )
    return users


@router.patch("/admin/users/{user_id}/role", response_model=UserPublic)
async def admin_update_role(
    user_id: str,
    data: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    roles = get_user_roles(request)
    if "superadmin" not in roles:
        raise AuthorizationError("superadmin access required")
    svc = AuthService(db)
    return await svc.admin_update_role(
        admin_id=get_user_id(request),
        admin_role=roles[0],
        target_user_id=user_id,
        new_role=UserRole(data.role),
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


@router.patch("/admin/users/{user_id}/ban", response_model=UserPublic)
async def admin_ban_user(
    user_id: str,
    data: BanUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    roles = get_user_roles(request)
    if "admin" not in roles and "superadmin" not in roles:
        raise AuthorizationError("admin access required")
    svc = AuthService(db)
    return await svc.admin_ban_user(
        admin_id=get_user_id(request),
        admin_role=roles[0],
        target_user_id=user_id,
        is_banned=data.is_banned,
        reason=data.reason,
        ip=request.client.host if request.client else "",
        correlation_id=get_correlation_id(request),
    )


# Router aggregation
api_router = APIRouter()
api_router.include_router(router)
