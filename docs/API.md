# API Reference

Base URL: `http://localhost:8080` (via API Gateway)

## Authentication

Semua endpoint (kecuali `Public`) memerlukan header:
```
Authorization: Bearer <access_token>
```

Token didapat dari `POST /api/v1/auth/login`.

Untuk operasi kritis (checkout, payment), wajib sertakan:
```
Idempotency-Key: <uuid-v4>
```

---

## Auth Service

### POST /api/v1/auth/register
**Public**. Register user baru.

Request:
```json
{
  "email": "user@example.com",
  "password": "StrongPassword123!",
  "full_name": "John Doe",
  "phone": "+6281234567890",
  "role": "buyer"
}
```

Response 201:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "role": "buyer",
    ...
  }
}
```

### POST /api/v1/auth/login
**Public**. Login.

Request:
```json
{
  "email": "user@example.com",
  "password": "StrongPassword123!",
  "mfa_code": "123456"  // optional, jika MFA enabled
}
```

Response 200: TokenResponse
Response 403 (MFA required):
```json
{
  "error": "mfa_required",
  "message": "mfa code required",
  "details": {
    "mfa_token": "...",
    "email": "user@example.com"
  }
}
```

### POST /api/v1/auth/refresh
**Public**. Refresh access token.

Request:
```json
{ "refresh_token": "eyJ..." }
```

Response 200: TokenResponse

### POST /api/v1/auth/logout
**Authenticated**. Revoke all sessions.

### POST /api/v1/auth/forgot-password
**Public**. Request password reset email.

### POST /api/v1/auth/reset-password
**Public**. Reset password dengan token.

### GET /api/v1/users/me
**Authenticated**. Get current user profile.

### PUT /api/v1/users/me
**Authenticated**. Update profile.

### POST /api/v1/users/me/change-password
**Authenticated**. Change password (revoke all sessions).

### POST /api/v1/users/me/mfa/setup
**Authenticated**. Setup MFA — returns secret & otpauth URI.

### POST /api/v1/users/me/mfa/verify
**Authenticated**. Verify MFA setup with first code.

### GET /api/v1/admin/users
**Admin+**. List users dengan filter role.

### PATCH /api/v1/admin/users/:id/role
**Superadmin**. Update user role.

### PATCH /api/v1/admin/users/:id/ban
**Admin+**. Ban/unban user.

---

## Catalog Service

### GET /api/v1/products
**Public**. List products dengan filter.

Query params:
- `search` — search by name
- `category_id` — filter by category
- `min_price`, `max_price` — price range
- `sort_by` — `created` | `price` | `name` | `updated`
- `sort_dir` — `asc` | `desc`
- `page`, `size` — pagination

Response 200:
```json
{
  "content": [ProductResponse],
  "pageable": {...},
  "totalElements": 100,
  "totalPages": 5
}
```

### GET /api/v1/products/:id
**Public**. Get product detail.

### POST /api/v1/products
**Seller+**. Create product.

### PUT /api/v1/products/:id
**Seller+** (owner or admin). Update product.

### DELETE /api/v1/products/:id
**Seller+** (owner or admin). Soft delete product.

### PATCH /api/v1/products/:id/stock
**Seller+**. Adjust stock.

### GET /api/v1/categories
**Public**. List categories.

---

## Order Service

### GET /api/v1/cart
**Authenticated (buyer, seller)**. Get current user cart.

### POST /api/v1/cart
**Authenticated (buyer, seller)**. Add item to cart.

Request:
```json
{
  "product_id": "uuid",
  "quantity": 2
}
```

### PUT /api/v1/cart/:item_id
**Authenticated**. Update cart item quantity.

### DELETE /api/v1/cart/:item_id
**Authenticated**. Remove item from cart.

### DELETE /api/v1/cart
**Authenticated**. Clear cart.

### POST /api/v1/checkout
**Authenticated (buyer)**. Checkout cart → create order.

Headers:
```
Idempotency-Key: <uuid-v4>
```

Request:
```json
{
  "shipping_address": "Jl. Sudirman No. 1, Jakarta",
  "payment_method": "credit_card"
}
```

Response 201:
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "status": "PENDING",
  "total_amount": "150000.00",
  "currency": "IDR",
  "expires_at": "2026-06-21T10:15:00Z",
  "items": [...]
}
```

### GET /api/v1/orders
**Authenticated**. List user orders.

### GET /api/v1/orders/:id
**Authenticated**. Get order detail.

### POST /api/v1/orders/:id/cancel
**Authenticated**. Cancel order (release stock reservation).

---

## Payment Service

### POST /api/v1/payments
**Authenticated (buyer)**. Create payment untuk order.

Headers:
```
Idempotency-Key: <uuid-v4>
```

Request:
```json
{
  "order_id": "uuid",
  "method": "credit_card",
  "provider": "midtrans"
}
```

Response 201:
```json
{
  "id": "uuid",
  "order_id": "uuid",
  "user_id": "uuid",
  "amount": "150000.00",
  "currency": "IDR",
  "status": "SUCCEEDED",
  "method": "credit_card",
  "provider": "midtrans",
  "provider_tx_id": "abc-123"
}
```

### GET /api/v1/payments/:id
**Authenticated**. Get payment detail (owner only).

### POST /api/v1/payments/:id/refund
**Admin+**. Refund payment.

### POST /api/v1/withdrawals
**Seller+**. Request withdrawal.

### GET /api/v1/withdrawals
**Seller+**. List own withdrawals.

### PATCH /api/v1/withdrawals/:id/approve
**Admin+**. Approve/reject withdrawal.

---

## Audit Service

### GET /api/v1/admin/audit
**Superadmin**. List audit log entries.

Query params:
- `action` — filter by action (e.g. `user.register`)
- `actor_user_id` — filter by actor
- `resource_type`, `resource_id` — filter by resource
- `start`, `end` — timestamp range (ISO 8601)
- `page`, `size` — pagination

### GET /api/v1/admin/errors
**Admin+**. List error log entries.

### GET /api/v1/admin/audit/verify
**Superadmin**. Verify hash chain integrity.

Query params:
- `start`, `end` — timestamp range

Response:
```json
{
  "total_entries": 1000,
  "broken_links": 0,
  "verified": true,
  "period": { "start": "...", "end": "..." }
}
```

---

## Common Error Response Format

Semua error response mengikuti format:

```json
{
  "error": "error_code",
  "message": "User-friendly message",
  "details": {},
  "request_id": "uuid",
  "correlation_id": "uuid"
}
```

### Status Codes

| Code | Error | Description |
|------|-------|-------------|
| 400 | `validation_error` | Input tidak valid |
| 401 | `unauthorized` | Token tidak ada/invalid/expired |
| 403 | `forbidden` | Authenticated tapi tidak punya akses |
| 404 | `not_found` | Resource tidak ditemukan |
| 409 | `conflict` | Conflict (e.g. duplicate, concurrent update) |
| 413 | `request_too_large` | Body > max_request_size |
| 422 | `validation_error` | Business rule violation |
| 423 | `account_locked` | Account locked karena failed login |
| 429 | `rate_limit_exceeded` | Rate limit hit |
| 500 | `internal_error` | Unexpected error (sudah di-log) |
| 503 | `service_unavailable` | Service unavailable |

### Rate Limit Headers
```
X-RateLimit-Remaining: 95
Retry-After: 60
```

---

## Idempotency

Untuk endpoint `POST /api/v1/checkout` dan `POST /api/v1/payments`, wajib sertakan header:

```
Idempotency-Key: <uuid-v4>
```

Jika request dengan key sama dikirim lagi dalam 24 jam, server akan return response yang sama dengan header:

```
X-Idempotent-Replay: true
```

Jika key tidak disertakan pada endpoint yang wajib, server return:
```json
{
  "error": "missing_idempotency_key",
  "message": "Idempotency-Key header required for this operation"
}
```

---

## Pagination

List endpoints pakai format:
```json
{
  "data": [...],
  "total": 100,
  "page": 0,
  "size": 20
}
```

Atau (Java/Spring):
```json
{
  "content": [...],
  "pageable": { "pageNumber": 0, "pageSize": 20 },
  "totalElements": 100,
  "totalPages": 5
}
```

Query params:
- `page` — 0-indexed (default: 0)
- `size` — items per page (default: 20, max: 100)

---

## Webhooks

### Midtrans Webhook
```
POST /internal/webhooks/midtrans
Headers:
  X-Internal-Token: <internal_token>
```

### Xendit Webhook
```
POST /internal/webhooks/xendit
Headers:
  X-Internal-Token: <internal_token>
```

---

## OpenAPI Specs

Swagger UI tersedia (development only):
- API Gateway: http://localhost:8080/docs
- Auth Service: http://localhost:8001/docs
- Catalog Service: http://localhost:8002/swagger-ui.html
- Order Service: (tidak ada, lihat dokumen ini)
- Payment Service: (tidak ada, lihat dokumen ini)
- Notification Service: http://localhost:8005/docs
- Audit Service: http://localhost:8006/docs

Production: Swagger dinonaktifkan untuk keamanan.
