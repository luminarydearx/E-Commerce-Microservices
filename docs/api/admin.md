# Admin API (Admin Service)

> Service: `admin-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8020

Central admin aggregator. Proxy ke multiple services untuk unified admin experience.

## Authorization

Semua endpoint memerlukan role `admin` atau `superadmin`. Audit endpoint hanya `superadmin`.

## Endpoints

### GET /admin/dashboard
Aggregate dashboard dari multiple services (analytics + fraud flags + system status).

```json
{
  "user_id": "uuid",
  "timestamp": "2026-06-21T10:00:00Z",
  "services": {
    "analytics": {...},
    "fraud_flags": {...}
  }
}
```

### GET /admin/system/health
Check status semua service.

```json
{
  "overall_status": "healthy",
  "services": {
    "auth-service": {"status": "up", "http_status": 200},
    "catalog-service": {"status": "up", "http_status": 200},
    "fraud-service": {"status": "down", "error": "connection timeout"}
  },
  "checked_at": "..."
}
```

### User Management (proxy ke auth-service)

- `GET /admin/users` - list users
- `PATCH /admin/users/{id}/role` - update role
- `PATCH /admin/users/{id}/ban` - ban/unban

### Audit Log (proxy ke audit-service, superadmin only)

- `GET /admin/audit` - list audit log entries with filter
- `GET /admin/errors` - list error log entries

### Seller Management (proxy ke seller-service)

- `POST /admin/sellers/{id}/verify` - verify seller
- `POST /admin/sellers/{id}/suspend` - suspend seller

### Fraud Management (proxy ke fraud-service)

- `GET /admin/fraud/flags` - list fraud flags
- `POST /admin/fraud/blocks/ip` - block IP
- `DELETE /admin/fraud/blocks/ip/{ip}` - unblock IP

## Pattern

Admin service bertindak sebagai **API aggregator**: menerima request admin, proxy ke service yang relevan dengan inject header `X-User-Id` dan `X-User-Roles`. Response di-aggregate dan return ke admin frontend.

Keuntungan:
- Frontend hanya perlu call 1 endpoint
- Auth check terpusat (admin-service verify role sebelum proxy)
- Bisa tambah business logic cross-service (e.g., "jika ban user, juga suspend all seller profiles")
