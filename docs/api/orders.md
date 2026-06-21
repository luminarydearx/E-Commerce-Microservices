# Orders API (Order Service)

> Service: `order-service` (Go)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8003`

Cart, checkout (saga pattern), order state machine, order tracking.

## Order State Machine

```
PENDING ──paid──▶ PAID ──confirmed──▶ CONFIRMED ──shipped──▶ SHIPPED ──delivered──▶ DELIVERED ──completed──▶ COMPLETED
   │                │                    │
   │                │                    └──cancelled──▶ CANCELLED
   │                │
   │                └──cancelled──▶ CANCELLED
   │                └──refunded──▶ REFUNDED
   │
   └──cancelled──▶ CANCELLED (release stock reservation)
```

Allowed transitions:
- `PENDING` → `PAID`, `CANCELLED`
- `PAID` → `CONFIRMED`, `CANCELLED`, `REFUNDED`
- `CONFIRMED` → `SHIPPED`, `CANCELLED`
- `SHIPPED` → `DELIVERED`
- `DELIVERED` → `COMPLETED`
- `CANCELLED`, `REFUNDED`, `COMPLETED` = terminal

## Checkout Saga Pattern

```
1. Order Service: create order (PENDING)            ──fail──▶ abort
2. Catalog Service: reserve stock (atomic SQL)      ──fail──▶ compensate: cancel order
3. Payment Service: charge payment                  ──fail──▶ compensate: release stock, cancel order
4. Order Service: confirm order (PAID)              ──fail──▶ compensate: refund payment, release stock
5. Notification Service: send confirmation email    ──fail──▶ log only (don't fail saga)
```

Setiap step punya compensating action. Jika gagal di tengah, saga coordinator jalankan compensation dalam urutan terbalik.

## Idempotency

Endpoint `POST /checkout` wajib menyertakan header:
```
Idempotency-Key: <uuid-v4>
```

Server simpan `(key, response)` di Redis 24 jam. Request kedua dengan key sama → return cached response dengan header `X-Idempotent-Replay: true`.

---

## Endpoints

### Cart Endpoints

#### GET /cart
Get atau create cart untuk user yang sedang login.

**Response 200 OK:**
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "items": [
    {
      "id": "uuid",
      "cart_id": "uuid",
      "product_id": "uuid",
      "quantity": 2,
      "unit_price": 18999000.00,
      "product_name": "iPhone 15 Pro 256GB",
      "seller_id": "uuid",
      "reserved": false,
      "reservation_id": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "expires_at": "2026-06-28T10:00:00Z",
  "created_at": "...",
  "updated_at": "..."
}
```

Cart auto-expire setelah 7 hari jika tidak ada aktivitas.

---

#### POST /cart
Tambah item ke cart (atau update quantity jika sudah ada).

**Request Body:**
```json
{
  "product_id": "uuid",
  "quantity": 2
}
```

**Behavior:**
- Fetch product info dari catalog-service (with retry)
- Validate: product ACTIVE, available_stock >= quantity
- Upsert: jika product sudah ada di cart → tambah quantity
- Price snapshot disimpan di cart_item (jika harga berubah, cart tetap pakai harga lama)

**Response 200 OK:** Updated cart

**Errors:**
- `400 Bad Request` - invalid quantity / cart limit reached (100 items)
- `409 Conflict` - insufficient stock

---

#### PUT /cart/{item_id}
Update quantity item di cart.

**Request Body:**
```json
{ "quantity": 3 }
```

---

#### DELETE /cart/{item_id}
Hapus item dari cart.

**Response 204 No Content**

---

#### DELETE /cart
Clear semua item di cart.

---

### Checkout & Orders

#### POST /checkout
Checkout cart → create order.

**Headers:** `Idempotency-Key: <uuid>` (WAJIB)

**Request Body:**
```json
{
  "shipping_address": "Jl. Sudirman No. 1, Jakarta Pusat, DKI Jakarta 10220",
  "payment_method": "credit_card"
}
```

**Behavior (saga):**
1. Validate cart tidak kosong
2. Calculate total dari semua items
3. Begin DB transaction (SERIALIZABLE)
4. Create order dengan status `PENDING`, expires_at = +15 menit
5. Create order_items
6. **Reserve stock** di catalog-service (HTTP call, with retry)
   - Jika gagal → release semua reservation yang sudah dibuat, return error
7. Commit transaction
8. Clear cart
9. Publish event `order.created`
10. Return order

**Response 201 Created:**
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "status": "PENDING",
  "total_amount": 37998000.00,
  "currency": "IDR",
  "shipping_address": "Jl. Sudirman No. 1, Jakarta",
  "shipping_cost": 0.00,
  "tax_amount": 0.00,
  "payment_method": "credit_card",
  "payment_id": null,
  "expires_at": "2026-06-21T10:15:00Z",
  "confirmed_at": null,
  "cancelled_at": null,
  "cancel_reason": null,
  "items": [
    {
      "id": "uuid",
      "order_id": "uuid",
      "product_id": "uuid",
      "product_name": "iPhone 15 Pro 256GB",
      "product_sku": "IPHONE-15-PRO-256",
      "quantity": 2,
      "unit_price": 18999000.00,
      "subtotal": 37998000.00,
      "reservation_id": "uuid",
      "seller_id": "uuid"
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

**Errors:**
- `400 Bad Request` - cart kosong / shipping_address kosong / payment_method kosong
- `409 Conflict` - insufficient stock (dengan detail product mana)
- `422 Validation Error` - terlalu banyak item (>50)

---

#### GET /orders
List order user.

**Query Params:**
- `page` (default 0)
- `size` (default 20, max 100)

**Response 200 OK:**
```json
{
  "data": [Order],
  "total": 50,
  "page": 0,
  "size": 20
}
```

---

#### GET /orders/{id}
Get detail order.

**Authorization:** Hanya owner order yang bisa lihat (cek `user_id`).

**Response 200 OK:** Order dengan items

**Errors:**
- `404 Not Found` - order tidak ada
- `403 Forbidden` - bukan owner

---

#### POST /orders/{id}/cancel
Cancel order (release stock reservation).

**Request Body:**
```json
{ "reason": "Changed my mind" }
```

**Behavior:**
- Hanya bisa cancel jika status `PENDING` atau `PAID`
- Jika sudah `CONFIRMED` → tidak bisa (sudah diproses seller)
- Release semua stock reservations
- Jika sudah paid → trigger refund via payment-service
- Publish event `order.cancelled`

**Response 200 OK:** Updated order

---

### Internal Endpoints (untuk payment-service, mTLS protected)

#### POST /internal/orders/{id}/payment-status
Update status payment untuk order (dipanggil payment-service setelah payment sukses/gagal).

**Request Body:**
```json
{
  "order_id": "uuid",
  "payment_id": "uuid",
  "status": "SUCCEEDED"
}
```

**Behavior:**
- Jika `SUCCEEDED`:
  - Cek transisi: PENDING → PAID (boleh)
  - Update order status → `PAID`
  - Set `payment_id` & `confirmed_at`
  - Confirm semua stock reservations di catalog-service
  - Publish event `order.paid`
- Jika `FAILED`:
  - Tetap di `PENDING` (user bisa retry payment)
  - Publish event `order.payment_failed`
  - Cron akan auto-cancel jika expired

**Response 204 No Content**

---

## Data Model

```sql
CREATE TABLE order_svc.carts (
    id UUID PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE TABLE order_svc.cart_items (
    id UUID PRIMARY KEY,
    cart_id UUID REFERENCES order_svc.carts(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    quantity INTEGER CHECK (quantity > 0),
    unit_price DECIMAL(19,2),
    product_name VARCHAR(255),
    seller_id UUID,
    reserved BOOLEAN DEFAULT FALSE,
    reservation_id UUID,
    UNIQUE(cart_id, product_id)
);

CREATE TABLE order_svc.orders (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    total_amount DECIMAL(19,2),
    currency VARCHAR(3) DEFAULT 'IDR',
    shipping_address TEXT,
    shipping_cost DECIMAL(19,2) DEFAULT 0,
    tax_amount DECIMAL(19,2) DEFAULT 0,
    payment_method VARCHAR(50),
    payment_id UUID,
    expires_at TIMESTAMPTZ,  -- 15 min to pay
    confirmed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancel_reason TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    version INTEGER DEFAULT 1,
    CONSTRAINT chk_order_status CHECK (status IN ('PENDING', 'PAID', 'CONFIRMED', 'SHIPPED', 'DELIVERED', 'COMPLETED', 'CANCELLED', 'REFUNDED'))
);

CREATE TABLE order_svc.order_items (
    id UUID PRIMARY KEY,
    order_id UUID REFERENCES order_svc.orders(id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    product_name VARCHAR(255),
    product_sku VARCHAR(100),
    quantity INTEGER CHECK (quantity > 0),
    unit_price DECIMAL(19,2),
    subtotal DECIMAL(19,2),
    reservation_id UUID,
    seller_id UUID,
    created_at TIMESTAMPTZ
);
```

## Concurrency Control

1. **Optimistic Locking**: kolom `version` di-check saat UPDATE
2. **SERIALIZABLE Isolation**: untuk checkout & payment update
3. **Atomic Stock Reservation**: SQL `UPDATE ... WHERE stock - reserved_stock >= qty` di catalog-service

## Failure Handling

### Stock reservation gagal di tengah saga
- Compensating action: release semua reservation yang sudah dibuat (reverse order)
- Order tidak di-commit
- Return error ke user dengan detail product mana yang insufficient

### Payment gagal
- Order tetap di `PENDING` (user bisa retry payment dalam 15 menit)
- Stock reservation tetap active (akan auto-expire jika order expired)
- Cron job auto-cancel order yang expired

### Order-service gagal notify ke payment-service
- Log error, jangan fail payment
- Reconciliation job harian untuk sinkronisasi

## Audit Events

- `order.created`
- `order.paid`
- `order.cancelled`
- `order.payment_failed`

Semua event ke Kafka topic `ecommerce.order.events`.
