# Shipping API (Shipping Service)

> Service: `shipping-service` (Go)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8010`

Shipping cost calculation, tracking, shipment management. Integration dengan RajaOngkir untuk multi-courier.

## Endpoints

### POST /shipping/calculate
Calculate shipping cost dari origin ke destination untuk berbagai courier.

```json
{
  "origin": "152",  // city code from RajaOngkir
  "destination": "445",
  "weight": 1000,  // in grams
  "couriers": ["jne", "tiki", "pos", "sicepat", "jnt"]
}
```

**Response 200 OK:**
```json
{
  "origin": "152",
  "destination": "445",
  "weight": 1000,
  "rates": [
    {
      "courier": "jne",
      "courier_name": "JNE",
      "service": "REG",
      "service_name": "Regular",
      "cost": 18000,
      "etd": "2-3",
      "currency": "IDR"
    },
    {
      "courier": "jne",
      "courier_name": "JNE",
      "service": "YES",
      "service_name": "Next Day",
      "cost": 36000,
      "etd": "1",
      "currency": "IDR"
    }
  ],
  "cached": true
}
```

**Caching:** Rates di-cache di Redis 24 jam untuk kombinasi (origin, destination, weight).

### GET /shipping/track/{tracking_number}
Track shipment real-time.

**Response 200 OK:**
```json
{
  "tracking_number": "TRK123456789",
  "status": "in_transit",
  "history": [
    {
      "timestamp": "2026-06-21T08:00:00Z",
      "status": "picked_up",
      "location": "Jakarta Sorting Center",
      "note": "Package picked up by courier"
    },
    {
      "timestamp": "2026-06-21T20:00:00Z",
      "status": "in_transit",
      "location": "Transit Hub Bandung",
      "note": "Package in transit"
    }
  ]
}
```

### GET /shipping/history
List user's shipment history.

### Internal Endpoints (mTLS protected)

#### POST /internal/shipments
Create shipment (called by order-service setelah payment confirmed).

```json
{
  "order_id": "uuid",
  "origin": "152",
  "destination": "445",
  "weight": 1000,
  "courier": "jne",
  "service": "REG",
  "recipient_name": "John Doe",
  "recipient_phone": "+6281234567890",
  "recipient_address": "Jl. Sudirman No. 1, Jakarta"
}
```

Response: tracking_number + provider info.

#### PATCH /internal/shipments/{id}/status
Update shipment status (called by webhook dari courier).

Shipment statuses: `CREATED` → `PICKED_UP` → `IN_TRANSIT` → `OUT_FOR_DELIVERY` → `DELIVERED` (or `FAILED_DELIVERY`/`RETURNED`/`CANCELLED`).

## Integration

### RajaOngkir
- API Key dari env `RAJA_ONGKIR_KEY`
- Endpoint: `https://api.rajaongkir.com/starter/cost`
- Couriers: JNE, POS, TIKI, SiCepat, J&T
- Cache 24 jam di Redis

### Other providers (planned)
- SiCepat direct API
- J&T direct API
- Lalamove for same-day delivery
