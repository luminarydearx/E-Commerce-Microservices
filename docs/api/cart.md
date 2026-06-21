# Cart API (Order Service)

> Service: `order-service` (Go)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8003`

User shopping cart dengan price snapshot, auto-expire 7 hari, max 100 items.

## Endpoints

### GET /cart
Get atau create cart untuk user yang sedang login.

**Response 200 OK:**
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "items": [
    {
      "id": "uuid",
      "product_id": "uuid",
      "quantity": 2,
      "unit_price": 18999000.00,
      "product_name": "iPhone 15 Pro",
      "seller_id": "uuid",
      "reserved": false
    }
  ],
  "expires_at": "2026-06-28T10:00:00Z"
}
```

### POST /cart
Add item ke cart. Auto-fetch product info dari catalog-service.

```json
{
  "product_id": "uuid",
  "quantity": 2
}
```

Validasi: product ACTIVE, stock available, cart max 100 items, max 99 qty per item.

### PUT /cart/{item_id}
Update quantity item.

### DELETE /cart/{item_id}
Hapus item.

### DELETE /cart
Clear cart.

## Behavior

- **Price snapshot**: harga disimpan saat add to cart, tidak berubah meski seller update harga
- **Auto-refresh expiry**: setiap GET cart extend expiry 7 hari
- **Stock validation**: cek available_stock real-time saat add
- **Cart persistence**: cart disimpan di DB, tidak hilang saat logout/login
