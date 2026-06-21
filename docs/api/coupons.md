# Coupons API (Coupon Service)

> Service: `coupon-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8009`

Voucher & coupon system: discount, flash sale voucher, stackable rules, redemption limits.

## Coupon Types

- `PERCENTAGE` - diskon persen (e.g. 10% off)
- `FIXED` - diskon nominal (e.g. Rp 50.000 off)
- `FREE_SHIPPING` - gratis ongkir

## Endpoints

### Admin Endpoints (admin/seller)

#### POST /admin/coupons
Create coupon baru.

```json
{
  "code": "HEMAT10",
  "name": "Diskon 10% Capai Rp 100rb",
  "description": "Berlaku untuk minimal belanja Rp 500rb",
  "discount_type": "PERCENTAGE",
  "discount_value": 10,
  "max_discount": 100000,
  "min_purchase": 500000,
  "max_usage_global": 10000,
  "max_usage_per_user": 1,
  "start_at": "2026-07-01T00:00:00Z",
  "end_at": "2026-07-31T23:59:59Z",
  "applicable_scope": "ALL",
  "is_stackable": false
}
```

Scope options: `ALL`, `CATEGORY`, `PRODUCT`, `SELLER` (kombinasi dengan `applicable_ids`)

#### GET /admin/coupons
List semua coupon.

#### PATCH /admin/coupons/{id}/deactivate
Nonaktifkan coupon sebelum waktunya berakhir.

### User Endpoints

#### POST /coupons/validate
Validate coupon terhadap cart. Tidak mengurangi quota, hanya cek.

```json
{
  "code": "HEMAT10",
  "user_id": "uuid",
  "cart_total": 750000,
  "cart_items": [
    {"product_id": "uuid", "category_id": "uuid", "seller_id": "uuid", "price": 750000, "quantity": 1}
  ]
}
```

**Response 200 OK:**
```json
{
  "valid": true,
  "discount_type": "PERCENTAGE",
  "discount_amount": 75000,
  "coupon_id": "uuid",
  "code": "HEMAT10",
  "name": "Diskon 10% Capai Rp 100rb"
}
```

**Validation checks:**
1. Coupon exists & active
2. Within validity period (start_at, end_at)
3. Global quota not exceeded (max_usage_global_count < max_usage_global)
4. Per-user quota not exceeded
5. User-specific coupon: user ada di whitelist
6. Min purchase met
7. Applicable scope check (ALL/CATEGORY/PRODUCT/SELLER)

#### POST /coupons/apply
Apply coupon ke order (record redemption). Idempotent per order_id.

```json
{
  "code": "HEMAT10",
  "user_id": "uuid",
  "order_id": "uuid",
  "discount_amount": 75000
}
```

Atomically increment `max_usage_global_count` + insert redemption record.

#### GET /users/{user_id}/coupons
List coupon yang available untuk user (yang masih bisa dipakai).

## Data Model

```sql
CREATE TABLE coupon.coupons (
    id UUID PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    discount_type VARCHAR(20) NOT NULL,
    discount_value INTEGER NOT NULL,
    max_discount INTEGER,
    min_purchase INTEGER DEFAULT 0,
    max_usage_global INTEGER DEFAULT 1,
    max_usage_per_user INTEGER DEFAULT 1,
    max_usage_global_count INTEGER DEFAULT 0,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    applicable_scope VARCHAR(20) DEFAULT 'ALL',
    applicable_ids JSONB,
    user_specific BOOLEAN DEFAULT FALSE,
    user_ids JSONB,
    is_stackable BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE coupon.coupon_redemptions (
    id UUID PRIMARY KEY,
    coupon_id UUID REFERENCES coupon.coupons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    order_id UUID NOT NULL UNIQUE,
    discount_amount INTEGER NOT NULL,
    redeemed_at TIMESTAMPTZ
);
```

## Concurrency

- Atomic increment dengan row lock pada redemption
- Idempotent: 1 order = 1 coupon (unique constraint `order_id`)
