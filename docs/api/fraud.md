# Fraud Detection API (Fraud Service)

> Service: `fraud-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8017`

Rule-based + ML fraud detection untuk transactions. Auto-block IP, challenge MFA, flag untuk review.

## Detection Rules

| Rule | Trigger | Score Added |
|------|---------|-------------|
| `BLOCKED_IP` | IP on blocklist | +1.0 (instant block) |
| `BLOCKED_USER` | User on blocklist | +1.0 (instant block) |
| `VELOCITY_FAILED_PAYMENT` | 3+ failed payments in 10 min | +0.4 |
| `HIGH_ORDER_VELOCITY` | 10+ orders in 1 hour | +0.3 |
| `LARGE_ORDER` | Order > Rp 50 juta | +0.15 |
| `VERY_LARGE_ORDER` | Order > Rp 100 juta | +0.3 |
| `NEW_ACCOUNT_LARGE_ORDER` | New account + order > Rp 5 juta | +0.3 |
| `MULTIPLE_REGISTRATIONS_IP` | 3+ registrations from IP in 1 min | +0.6 |

## Score Thresholds

- **Score >= 0.7** → `BLOCKED` (auto-block IP 1 jam)
- **Score >= 0.4** → `CHALLENGED` (require MFA/CAPTCHA)
- **Score < 0.4** → `ALLOWED`

## Endpoints

### POST /internal/fraud/check
Internal: Check transaction untuk fraud (dipanggil oleh service lain sebelum process transaction).

```json
{
  "user_id": "uuid",
  "ip_address": "1.2.3.4",
  "device_id": "fingerprint-hash",
  "amount": 55000000,
  "transaction_type": "ORDER",
  "context": {}
}
```

Transaction types: `ORDER`, `PAYMENT`, `REGISTER`, `LOGIN`, `WITHDRAWAL`

**Response 200 OK:**
```json
{
  "score": 0.45,
  "action": "CHALLENGED",
  "flags": [
    {
      "rule": "LARGE_ORDER",
      "severity": "info",
      "description": "Large order amount: 55000000"
    }
  ],
  "requires_mfa": true,
  "transaction_id": "uuid"
}
```

Jika `action=BLOCKED`, IP otomatis di-block 1 jam di fraud.blocked_ips table.

### GET /admin/fraud/flags
List fraud flags (admin only). Filter by status (`OPEN`, `REVIEWING`, `RESOLVED`, `FALSE_POSITIVE`).

### POST /admin/fraud/blocks/ip
Manual block IP (admin).

```json
{
  "ip_address": "1.2.3.4",
  "reason": "Coordinated fraud attack",
  "hours": 24
}
```

`hours: null` = permanent block.

### DELETE /admin/fraud/blocks/ip/{ip}
Unblock IP.

## ML Model (Planned)

Selain rule-based, akan ada ML model (XGBoost / Isolation Forest) yang trained dari historical fraud data:
- Features: device fingerprint, behavioral biometric, graph anomaly
- Threshold: score > 0.7 → block, 0.4-0.7 → challenge
- Retrain weekly dengan labeled data

## Audit Events

- `fraud.flag_raised`
- `fraud.ip_blocked` (auto & manual)
- `fraud.user_blocked`
- `fraud.flag_resolved`
