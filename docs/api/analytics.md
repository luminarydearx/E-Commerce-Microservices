# Analytics API (Analytics Service)

> Service: `analytics-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8019`

Business intelligence dashboard: GMV, conversion funnel, cohort retention, realtime metrics.

## Endpoints (Admin Only)

### GET /analytics/overview
High-level KPIs.

**Query:** `period` = `7d` / `30d` / `90d` / `1y`

**Response:**
```json
{
  "period": "30d",
  "kpis": {
    "gmv": 1500000000,
    "gmv_change_pct": 12.5,
    "orders_count": 15420,
    "orders_change_pct": 8.3,
    "active_users": 8234,
    "users_change_pct": 5.2,
    "conversion_rate": 3.4,
    "avg_order_value": 97000,
    "refund_rate": 1.2,
    "payment_success_rate": 98.5
  },
  "trend": [
    {"date": "2026-05-22", "gmv": 50000000, "orders": 500}
  ]
}
```

### GET /analytics/funnel
Conversion funnel: view → cart → checkout → paid → delivered.

```json
{
  "stages": [
    {"stage": "view", "count": 1000000, "rate": 100.0},
    {"stage": "add_to_cart", "count": 50000, "rate": 5.0},
    {"stage": "checkout", "count": 30000, "rate": 3.0},
    {"stage": "paid", "count": 28500, "rate": 2.85},
    {"stage": "delivered", "count": 27000, "rate": 2.7}
  ],
  "drop_off_points": [
    {"from": "view", "to": "add_to_cart", "drop_pct": 95.0}
  ]
}
```

### GET /analytics/top-products
Top selling products.

### GET /analytics/top-sellers
Top sellers by GMV.

### GET /analytics/cohort
User retention by signup cohort (monthly).

### GET /analytics/realtime
Real-time metrics (last 5 minutes).

```json
{
  "active_users": 234,
  "active_carts": 89,
  "orders_last_5min": 12,
  "revenue_last_5min": 4500000,
  "active_flash_sale_users": 1234,
  "payment_processing": 8,
  "ws_connections": 56
}
```

### POST /analytics/track
Track custom event dari frontend (anonymized user_id).

```json
{
  "event": "product_viewed",
  "user_id": "hash",
  "properties": {
    "product_id": "uuid",
    "source": "search"
  }
}
```

Untuk funnel analysis & A/B testing.
