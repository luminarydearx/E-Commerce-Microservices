# Seller API (Seller Service)

> Service: `seller-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8018`

Seller profile, dashboard, analytics, performance metrics, trust badge.

## Trust Badges

| Badge | Trust Score | Requirements |
|-------|-------------|--------------|
| NEW | 0-39 | Default |
| BRONZE | 40-59 | Verified KTP |
| SILVER | 60-79 | + 100 orders, rating 4.0+ |
| GOLD | 80-94 | + 1000 orders, rating 4.5+, fulfillment 95%+ |
| PLATINUM | 95-100 | + 10000 orders, rating 4.8+, fulfillment 99%+ |

## Endpoints

### GET /seller/profile
Get seller profile user yang login.

### POST /seller/profile
Create/update seller profile (store name, description, logo, bank account).

### GET /seller/dashboard
Get dashboard dengan metrics.

**Query:** `period` = `7d` / `30d` / `90d` / `1y`

**Response:**
```json
{
  "period": "30d",
  "summary": {
    "total_revenue": 150000000,
    "total_orders": 234,
    "total_products_sold": 412,
    "avg_rating": 4.7,
    "total_views": 12450
  },
  "daily": [
    {
      "date": "2026-06-21",
      "revenue": 5000000,
      "orders": 8,
      "products_sold": 15,
      "rating": 4.8
    }
  ],
  "profile": {
    "store_name": "Top Store",
    "trust_badge": "GOLD",
    "rating_avg": 4.7,
    "fulfillment_rate": 96.5
  }
}
```

### GET /seller/products
List produk seller (proxy ke catalog-service dengan filter seller_id).

### GET /seller/orders
List orders yang contain produk seller.

### GET /seller/analytics/top-products
Top selling products untuk seller.

### Admin Endpoints

#### POST /admin/sellers/{seller_id}/verify
Verify seller (KTP/NPWP verified). Trust score +20.

#### POST /admin/sellers/{seller_id}/suspend
Suspend seller (untuk violation). Set `is_suspended=true`, `is_active=false`.

```json
{ "reason": "Selling counterfeit products" }
```
