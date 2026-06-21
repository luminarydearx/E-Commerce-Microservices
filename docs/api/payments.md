# Payments API (Payment Service)

> Service: `payment-service` (Go)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8004`

Payment processing, refund, withdrawal. Full idempotency, saga pattern, multi-provider (Midtrans/Xendit).

## Payment State Machine

```
PENDING ──succeeded──▶ SUCCEEDED ──refunded──▶ REFUNDED
   │                      │
   │                      └──partial_refund──▶ PARTIAL_REFUND ──refunded──▶ REFUNDED
   │
   └──failed──▶ FAILED (terminal)
```

## Idempotency

Semua endpoint POST/PUT wajib header:
```
Idempotency-Key: <uuid-v4>
```

Redis cache 24 jam. Request kedua dengan key sama → return cached response.

---

## Endpoints

### POST /payments
Create payment untuk order.

**Headers:** `Idempotency-Key: <uuid>` (WAJIB)

**Request Body:**
```json
{
  "order_id": "uuid",
  "method": "credit_card",
  "provider": "midtrans"
}
```

**Methods supported:**
- `credit_card` - Visa/Mastercard via 3DS
- `bank_transfer` - VA BCA/Mandiri/BNI/BRI
- `e_wallet` - GoPay/OVO/DANA/ShopeePay
- `qris` - QRIS
- `retail_outlet` - Alfamart/Indomaret
- `bnpl` - Kredivo/Akulaku

**Providers:**
- `midtrans` - default
- `xendit` - alternative

**Behavior (saga):**
1. Idempotency check: jika sudah ada payment dengan key sama → return existing
2. Fetch order dari order-service (verify milik user, status PENDING, belum expired)
3. Check jika sudah ada payment sukses untuk order ini → return 400
4. Create payment record (status PENDING)
5. Call provider API (Midtrans/Xendit) dengan retry
6. Update payment status → SUCCEEDED + provider_tx_id
7. Notify order-service untuk update order status → PAID
8. Publish event `payment.succeeded`

**Response 201 Created:**
```json
{
  "id": "uuid",
  "order_id": "uuid",
  "user_id": "uuid",
  "amount": 37998000.00,
  "currency": "IDR",
  "status": "SUCCEEDED",
  "method": "credit_card",
  "provider": "midtrans",
  "provider_tx_id": "midtrans-abc-123",
  "provider_response": "{...}",
  "failure_reason": null,
  "idempotency_key": "uuid-v4",
  "refunded_amount": 0.00,
  "created_at": "...",
  "updated_at": "..."
}
```

**Errors:**
- `400 Bad Request` - order not in payable state / expired / already paid
- `403 Forbidden` - order bukan milik user
- `422 Validation Error` - invalid provider/method

---

### GET /payments/{id}
Get detail payment (owner only).

**Response 200 OK:** PaymentResponse

---

### POST /payments/{id}/refund
Refund payment (admin/superadmin only).

**Request Body:**
```json
{
  "amount": "1000000",
  "reason": "Customer complaint - damaged item"
}
```

**Behavior:**
- Hanya bisa refund jika status `SUCCEEDED` atau `PARTIAL_REFUND`
- Total refund tidak boleh melebihi amount asli
- Partial refund: status jadi `PARTIAL_REFUND`
- Full refund (refunded_amount == amount): status jadi `REFUNDED`
- Async call provider refund API (best-effort, reconcile if fail)

**Response 200 OK:**
```json
{
  "id": "uuid",
  "payment_id": "uuid",
  "amount": 1000000.00,
  "reason": "Customer complaint",
  "status": "PENDING",
  "provider_ref_id": null,
  "created_by": "uuid-admin",
  "created_at": "..."
}
```

---

### POST /withdrawals
Seller request withdrawal (role: seller/admin).

**Request Body:**
```json
{
  "amount": "5000000",
  "bank_account": "1234567890",
  "bank_code": "bca",
  "account_holder": "John Doe"
}
```

**Behavior:**
- Min withdrawal: Rp 10.000
- Auto-approve jika <= Rp 1.000.000 (configurable)
- Manual review jika > Rp 1.000.000
- Publish event `withdrawal.requested`

---

### GET /withdrawals
List seller's own withdrawals.

---

### PATCH /withdrawals/{id}/approve
Admin approve/reject withdrawal.

**Request Body:**
```json
{
  "approve": true,
  "reason": "verified"
}
```

---

### Internal Endpoints

#### POST /internal/webhooks/midtrans
Webhook dari Midtrans (mTLS protected + signature verify).

#### POST /internal/webhooks/xendit
Webhook dari Xendit.

---

## Data Model

```sql
CREATE TABLE payment_svc.payments (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL,
    user_id UUID NOT NULL,
    amount DECIMAL(19,2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) DEFAULT 'IDR',
    status VARCHAR(20) DEFAULT 'PENDING',
    method VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    provider_tx_id VARCHAR(255),
    provider_response TEXT,
    failure_reason TEXT,
    idempotency_key VARCHAR(64) UNIQUE,
    refunded_amount DECIMAL(19,2) DEFAULT 0,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    version INTEGER DEFAULT 1,
    CONSTRAINT chk_payment_status CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'REFUNDED', 'PARTIAL_REFUND')),
    CONSTRAINT chk_refunded CHECK (refunded_amount >= 0 AND refunded_amount <= amount)
);

CREATE TABLE payment_svc.refunds (
    id UUID PRIMARY KEY,
    payment_id UUID REFERENCES payment_svc.payments(id) ON DELETE RESTRICT,
    amount DECIMAL(19,2) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    provider_ref_id VARCHAR(255),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE TABLE payment_svc.withdrawals (
    id UUID PRIMARY KEY,
    seller_id UUID NOT NULL,
    amount DECIMAL(19,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'IDR',
    status VARCHAR(20) DEFAULT 'PENDING',
    bank_account VARCHAR(50),
    bank_code VARCHAR(20),
    account_holder VARCHAR(255),
    provider_ref_id VARCHAR(255),
    notes TEXT,
    processed_by UUID,
    processed_at TIMESTAMPTZ,
    version INTEGER DEFAULT 1,
    CONSTRAINT chk_withdrawal_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'PAID', 'FAILED'))
);
```

## Audit Events

- `payment.succeeded`
- `payment.failed`
- `payment.refunded`
- `withdrawal.requested`
- `withdrawal.approved`
- `withdrawal.rejected`
