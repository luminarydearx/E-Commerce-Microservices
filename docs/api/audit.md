# Audit API (Audit Service)

> Service: `audit-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8006`

Centralized audit log & error tracking dengan hash chain (tamper-evident), PII auto-redaction.

## Audit Log Features

### Hash Chain (Tamper-Evident)

Setiap row audit log punya:
- `prev_hash` - hash row sebelumnya
- `row_hash` - SHA256(timestamp + producer + action + actor + resource + before + after + prev_hash)

Jika row di-modify, chain putus → detectable via `verify_chain` endpoint.

### PII Auto-Redaction

PII di error log di-replace otomatis:
- Email → `[REDACTED_EMAIL]`
- Phone (+62...) → `[REDACTED_PHONE]`
- Credit card (16 digit) → `[REDACTED_CARD]`

Field `pii_redacted=true` di row yang sudah di-redact.

### Error Fingerprinting

Error dengan fingerprint sama di-group jadi 1 issue. Fingerprint = MD5(service + error_type + sanitized_stack_trace).

## Endpoints

### GET /admin/audit
List audit log entries (superadmin only).

**Query Params:**
- `action` - filter by action (e.g. `user.register`)
- `actor_user_id` - filter by actor
- `resource_type`, `resource_id` - filter by resource
- `start`, `end` - timestamp range (ISO 8601)
- `page`, `size` - pagination

**Response:**
```json
{
  "data": [
    {
      "audit_id": "uuid",
      "timestamp": "2026-06-21T10:00:00Z",
      "producer": "auth-service",
      "action": "user.login",
      "actor_user_id": "uuid",
      "actor_ip": "1.2.3.4",
      "resource_type": "user",
      "resource_id": "uuid",
      "before": null,
      "after": null,
      "correlation_id": "uuid",
      "event_id": "uuid",
      "row_hash": "abc123..."
    }
  ],
  "total": 14520,
  "page": 0,
  "size": 50
}
```

### GET /admin/errors
List error log entries (admin+).

**Query Params:**
- `service` - filter by service name
- `level` - filter by level (error/warning/fatal)
- `fingerprint` - filter by fingerprint (group similar errors)
- `page`, `size`

### POST /internal/errors
Endpoint untuk service push error langsung (sync fallback ke Kafka).

```json
{
  "service": "auth-service",
  "environment": "production",
  "level": "error",
  "error_type": "ValueError",
  "message": "Invalid token",
  "stack_trace": "...",
  "context": {"user_id": "uuid"},
  "request_id": "uuid",
  "correlation_id": "uuid",
  "user_id": "uuid"
}
```

### GET /admin/audit/verify
Verify hash chain integrity (superadmin only).

**Query:** `start`, `end` (timestamp range)

**Response:**
```json
{
  "total_entries": 14520,
  "broken_links": 0,
  "verified": true,
  "period": {"start": "...", "end": "..."}
}
```

Jika `broken_links > 0` → audit log di-tamper, alert critical.

## Anomaly Detection

Audit service consume events dan apply rule-based anomaly detection:

| Rule | Trigger | Action |
|------|---------|--------|
| `multiple_failed_logins` | 10+ failed login from IP in 5 min | Flag warning |
| `large_order_value` | Order > Rp 50 juta | Flag warning |
| `multiple_registrations` | 5+ registrations from IP in 1 min | Flag critical (bot) |
| `refund_spike` | 5+ refunds in 1 hour | Flag critical (abuse) |

Anomaly disimpan di `audit.anomaly_alerts` table dengan status `OPEN`. Admin resolve via dashboard.

## Data Retention

| Data | Retention |
|------|-----------|
| Application log (Loki) | 30 hari |
| Audit log (PostgreSQL) | 7 tahun (compliance) |
| Error log | 90 hari, then archive to S3 |
| Metrics | 90 hari |
| Traces | 7 hari |
