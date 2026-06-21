# Flash Sale API (Flash Sale Service)

> Service: `flashsale-service` (Go)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8015`

Flash sale dengan queue system anti-bot, atomic stock deduction via Redis Lua script.

## Anti-Bot & Anti-DDoS

1. **Queue system**: User harus join queue sebelum bisa beli. Hanya 1 user di depan queue yang dapat slot beli.
2. **Atomic stock deduction**: Redis Lua script untuk race condition safety
3. **Per-user purchase limit**: max 1 unit per user per flash sale item (configurable)
4. **Purchase token**: Setelah dapat slot, user dapat token valid 5 menit untuk checkout
5. **IP-based rate limit**: di API Gateway layer

## Endpoints

### Public Endpoints

#### GET /flash-sales/active
List flash sale yang sedang aktif.

```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Flash Sale 11.11",
      "start_at": "2026-11-11T00:00:00Z",
      "end_at": "2026-11-11T23:59:59Z",
      "status": "ACTIVE",
      "countdown_seconds": 54321
    }
  ]
}
```

#### GET /flash-sales/{id}
Get detail flash sale.

#### GET /flash-sales/{id}/items
List items dalam flash sale.

```json
{
  "data": [
    {
      "id": "uuid",
      "product_id": "uuid",
      "original_price": 18999000,
      "sale_price": 15999000,
      "quota": 100,
      "sold": 87,
      "remaining": 13,
      "max_per_user": 1,
      "discount_percent": 15
    }
  ]
}
```

### Buyer Endpoints

#### POST /flash-sales/{id}/join-queue
User join antrian untuk flash sale.

**Response 200 OK:**
```json
{
  "status": "queued",
  "position": 23,
  "estimated_wait_seconds": 115
}
```

**Response 429 (queue full):**
```json
{
  "error": "queue_full",
  "message": "please try again later"
}
```

Max queue size: 100.000 users.

#### GET /flash-sales/{id}/queue-status
Cek posisi antrian.

```json
{
  "position": 1,
  "can_buy": true,
  "estimated_wait_seconds": 0
}
```

#### POST /flash-sales/{id}/items/{item_id}/buy
Attempt buy (harus di posisi #1 queue).

**Atomic operations via Redis Lua script:**
1. Check user limit (max_per_user)
2. Check stock > 0
3. Decrement stock atomically
4. Increment user purchase count

**Response 200 OK:**
```json
{
  "status": "purchase_token_granted",
  "token": "uuid-token",
  "expires_in_seconds": 300,
  "message": "proceed to checkout with this token"
}
```

**Errors:**
- `403 Forbidden` - not_your_turn (masih antri)
- `400 Bad Request` - user_limit_reached / out_of_stock

### Admin Endpoints

#### POST /admin/flash-sales
Create flash sale baru.

#### POST /admin/flash-sales/{id}/items
Add product ke flash sale dengan quota & sale price.

```json
{
  "product_id": "uuid",
  "original_price": 18999000,
  "sale_price": 15999000,
  "quota": 100,
  "max_per_user": 1
}
```

Stock di-init di Redis via `SET fs:stock:{sale_id}:{item_id} {quota}`.

#### PATCH /admin/flash-sales/{id}/end
End flash sale lebih awal.

## Redis Keys

- `fs:queue:{sale_id}` - List berisi user_id yang antri (FIFO)
- `fs:queue:members:{sale_id}` - Set user yang sudah di queue (anti double-join)
- `fs:stock:{sale_id}:{item_id}` - Integer stock counter
- `fs:user_bought:{sale_id}:{item_id}:{user_id}` - Counter per user
- `fs:purchase_token:{token}` - String "sale_id:item_id:user_id", TTL 5 min
