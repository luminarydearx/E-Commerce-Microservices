# Wishlist API (Wishlist Service)

> Service: `wishlist-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8008`

Save products ke wishlist, price drop alerts, restock notifications.

## Endpoints

### GET /wishlist
Get user's wishlist + items.

### POST /wishlist/items
Add product ke wishlist.

```json
{
  "product_id": "uuid",
  "note": "Want to buy next month",
  "notify_price_drop": true,
  "notify_restock": false,
  "target_price": 15000000
}
```

### PUT /wishlist/items/{item_id}
Update item (note, notification preferences, target_price).

### DELETE /wishlist/items/{item_id}
Remove item dari wishlist.

### GET /wishlist/check/{product_id}
Check apakah product ada di wishlist user (untuk UI button toggle).

```json
{
  "in_wishlist": true,
  "item_id": "uuid"
}
```

### POST /internal/wishlist/price-update
Internal: triggered by catalog-service saat product price change. Auto-create price drop alerts untuk user yang notify_price_drop=true.

## Features

- **Price drop alert**: kirim notif saat harga turun ke bawah target_price
- **Restock notification**: kirim notif saat product yang sebelumnya out-of-stock kembali available
- **Multi-wishlist**: (planned) user bisa punya multiple wishlist dengan nama berbeda
