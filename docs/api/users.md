# Users API (Auth Service)

> Service: `auth-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8001`

Authentication & user management service. Handles registration, login, JWT, refresh token rotation, MFA, password reset, account lockout, RBAC.

## Authentication

All protected endpoints require header:
```
Authorization: Bearer <access_token>
```

Token diperoleh dari `POST /auth/login`. Token access berlaku 15 menit, refresh 7 hari.

## RBAC Roles

| Role | Permissions |
|------|-------------|
| `buyer` | product:read, cart:write, order:create, payment:create, review:write, profile:write:own |
| `seller` | semua buyer + product:write:own, withdrawal:request |
| `admin` | semua seller + user:read, user:ban, audit:read, config:read |
| `superadmin` | semua admin + user:role_change, config:write |

---

## Endpoints

### Public Endpoints (no auth required)

#### POST /auth/register
Register user baru.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongP@ss123!",
  "full_name": "John Doe",
  "phone": "+6281234567890",
  "role": "buyer"
}
```

**Validasi:**
- Email: format RFC 5322 + DNS MX check
- Password: min 12 char, 1 upper, 1 lower, 1 digit, 1 symbol, no common passwords
- Phone: format E.164 (`+62...`)
- Role: hanya `buyer` atau `seller` (admin/superadmin tidak bisa self-register)

**Response 201 Created:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "full_name": "John Doe",
    "phone": "+6281234567890",
    "role": "buyer",
    "is_email_verified": false,
    "is_phone_verified": false,
    "mfa_enabled": false,
    "created_at": "2026-06-21T10:00:00Z",
    "last_login_at": null
  }
}
```

**Errors:**
- `409 Conflict` - email sudah terdaftar
- `422 Validation Error` - password terlalu lemah / format invalid

**Rate Limit:** 5 req/min per IP (auth-specific limit)

**Security:**
- Password di-hash dengan Argon2id (memory-hard, GPU-resistant)
- Audit event `user.register` dipublish ke Kafka
- Email tidak di-reveal apakah sudah ada (di future): saat ini 409 untuk UX

---

#### POST /auth/login
Login user.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongP@ss123!",
  "mfa_code": "123456"
}
```

**Behavior:**
- Jika MFA enabled & `mfa_code` tidak dikirim → return `403 mfa_required` dengan `mfa_token`
- Jika 5x gagal login → account locked 30 menit
- Setiap login sukses → reset failed_login_attempts, update last_login_at
- Refresh token disimpan dengan hash SHA256 (tidak plain)

**Response 200 OK:** sama seperti register

**Response 403 MFA Required:**
```json
{
  "error": "mfa_required",
  "message": "mfa code required",
  "details": {
    "mfa_token": "abc123...",
    "email": "user@example.com"
  }
}
```

**Errors:**
- `401 Unauthorized` - email/password salah (pesan sama untuk keduanya, anti-enumeration)
- `403 mfa_required` - MFA enabled tapi kode tidak dikirim
- `423 Locked` - account locked karena terlalu banyak gagal

---

#### POST /auth/refresh
Refresh access token (rotation: revoke old, issue new).

**Request Body:**
```json
{ "refresh_token": "eyJ..." }
```

**Response 200 OK:** TokenResponse baru

**Security - Refresh Token Rotation:**
- Setiap refresh → revoke old refresh token, issue new pair
- Deteksi reuse: jika refresh token yang sudah di-revoke dipakai lagi → **revoke ALL user tokens** (kemungkinan token dicuri)
- Refresh token disimpan di DB dengan hash SHA256, bukan plain text

**Errors:**
- `401 Unauthorized` - token invalid/expired/reused

---

#### POST /auth/forgot-password
Request password reset link via email.

**Request Body:**
```json
{ "email": "user@example.com" }
```

**Response 200 OK:**
```json
{ "message": "if email exists, reset link has been sent" }
```

**Security:** Selalu return pesan sama meski email tidak ada (anti-enumeration). Token reset dikirim via email.

---

#### POST /auth/reset-password
Reset password dengan token dari email.

**Request Body:**
```json
{
  "token": "reset_token_from_email",
  "new_password": "NewStrongP@ss456!"
}
```

**Response 200 OK:**
```json
{ "message": "password has been reset" }
```

**Behavior:**
- Token berlaku 1 jam, sekali pakai
- Setelah reset: revoke ALL sessions user

---

### Authenticated Endpoints

#### POST /auth/logout
Revoke semua refresh token user.

**Headers:** `Authorization: Bearer <token>`

**Response 204 No Content**

---

#### GET /users/me
Get profil user yang sedang login.

**Response 200 OK:**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "phone": "+6281234567890",
  "role": "buyer",
  "is_email_verified": true,
  "is_phone_verified": false,
  "mfa_enabled": true,
  "created_at": "2026-06-21T10:00:00Z",
  "last_login_at": "2026-06-21T15:30:00Z"
}
```

---

#### PUT /users/me
Update profil user.

**Request Body (partial update):**
```json
{
  "full_name": "John Updated",
  "phone": "+629876543210"
}
```

**Response 200 OK:** Updated UserPublic

---

#### POST /users/me/change-password
Change password (jika user ingat password lama).

**Request Body:**
```json
{
  "current_password": "StrongP@ss123!",
  "new_password": "NewStrongP@ss456!"
}
```

**Response 204 No Content**

**Behavior:**
- Verifikasi password lama
- Password baru harus berbeda dari lama
- Setelah change: revoke ALL sessions (force re-login)

---

#### POST /users/me/mfa/setup
Setup MFA (TOTP seperti Google Authenticator).

**Request Body:**
```json
{ "password": "StrongP@ss123!" }
```

**Response 200 OK:**
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "otpauth_uri": "otpauth://totp/ECommerce:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=ECommerce"
}
```

Scan `otpauth_uri` sebagai QR code di aplikasi authenticator.

---

#### POST /users/me/mfa/verify
Verify setup MFA dengan kode pertama dari authenticator.

**Request Body:**
```json
{
  "code": "123456",
  "secret": "JBSWY3DPEHPK3PXP"
}
```

**Response 200 OK:**
```json
{ "mfa_enabled": true }
```

---

### Admin Endpoints (admin/superadmin only)

#### GET /admin/users
List semua user dengan filter.

**Query Params:**
- `role` - filter by role (`buyer`/`seller`/`admin`/`superadmin`)
- `page` - default 0
- `size` - default 20, max 100

**Response 200 OK:**
```json
[
  {
    "id": "uuid",
    "email": "user@example.com",
    "role": "buyer",
    "is_active": true,
    "is_banned": false,
    "is_locked": false,
    "created_at": "...",
    "last_login_at": "..."
  }
]
```

---

#### PATCH /admin/users/{user_id}/role
Ubah role user (superadmin only).

**Request Body:**
```json
{ "role": "seller" }
```

---

#### PATCH /admin/users/{user_id}/ban
Ban/unban user.

**Request Body:**
```json
{
  "is_banned": true,
  "reason": "spam reviews"
}
```

**Behavior:**
- Ban → revoke ALL sessions user
- Tidak bisa ban superadmin
- Audit event `admin.user_ban` di-publish

---

## Data Model

```sql
CREATE TABLE auth.users (
    id UUID PRIMARY KEY,
    email VARCHAR(255),
    email_lower VARCHAR(255) UNIQUE,  -- for case-insensitive lookup
    phone VARCHAR(20) UNIQUE,
    password_hash TEXT,  -- Argon2id
    role VARCHAR(20) DEFAULT 'buyer',
    is_active BOOLEAN DEFAULT TRUE,
    is_banned BOOLEAN DEFAULT FALSE,
    is_locked BOOLEAN DEFAULT FALSE,
    locked_until TIMESTAMPTZ,
    failed_login_attempts INTEGER DEFAULT 0,
    last_login_at TIMESTAMPTZ,
    last_login_ip INET,
    password_changed_at TIMESTAMPTZ,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(64),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    version INTEGER DEFAULT 1  -- optimistic lock
);

CREATE TABLE auth.refresh_tokens (
    id UUID PRIMARY KEY,
    user_id UUID,
    jti VARCHAR(64) UNIQUE,  -- JWT ID for revocation
    token_hash VARCHAR(128),  -- SHA256, not plain
    expires_at TIMESTAMPTZ,
    is_revoked BOOLEAN DEFAULT FALSE,
    user_agent TEXT,
    ip_address INET
);

CREATE TABLE auth.password_reset_tokens (
    id UUID PRIMARY KEY,
    user_id UUID,
    token_hash VARCHAR(128) UNIQUE,
    expires_at TIMESTAMPTZ,
    is_used BOOLEAN DEFAULT FALSE,
    used_at TIMESTAMPTZ
);
```

## Security Features

1. **Password Hashing**: Argon2id (memory cost 64MB, time cost 3, parallelism 4) — GPU-resistant
2. **JWT Signing**: RS256 (asymmetric) — private key hanya di auth-service
3. **Refresh Token Rotation**: revoke old, issue new setiap refresh
4. **Reuse Detection**: jika token revoked dipakai lagi → revoke ALL
5. **Account Lockout**: 5 failed attempts → 30 menit lock
6. **MFA**: TOTP (RFC 6238) via pyotp
7. **Rate Limit**: 5 req/min untuk auth endpoints
8. **Audit Log**: setiap aksi kritis (register, login, role change, ban, password change) di-log
9. **PII Protection**: email/phone tidak di-log di plain text

## Error Codes

| Code | HTTP | Description |
|------|------|-------------|
| `unauthorized` | 401 | Token invalid/expired |
| `forbidden` | 403 | Role tidak cukup |
| `account_locked` | 423 | Account locked karena failed login |
| `mfa_required` | 403 | MFA enabled, kode tidak dikirim |
| `validation_error` | 422 | Input invalid |
| `conflict` | 409 | Email sudah terdaftar |
| `rate_limit_exceeded` | 429 | Rate limit hit |

## Audit Events

Setiap aksi kritis mempublish event ke Kafka topic `ecommerce.audit.events`:

- `user.register`
- `user.login`
- `user.logout`
- `user.update`
- `user.password_change`
- `user.password_reset`
- `user.password_reset_requested`
- `user.mfa_enabled`
- `user.mfa_disabled`
- `token.refresh`
- `admin.role_change`
- `admin.user_ban`
- `admin.user_unban`
