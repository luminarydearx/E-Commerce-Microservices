# Audit & Error Tracking

## Overview

`audit-service` adalah sistem sentralisasi untuk:
1. **Audit log** — siapa melakukan apa, kapan, dari mana
2. **Error tracking** — aggregasi exception dengan stack trace
3. **Anomaly detection** — deteksi pattern mencurigakan
4. **Compliance reporting** — laporan untuk regulator/audit eksternal

---

## Audit Log

### Storage

**PostgreSQL** dengan schema append-only:
```sql
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    actor_user_id UUID,
    actor_role VARCHAR(50),
    actor_ip INET,
    actor_user_agent TEXT,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID,
    before JSONB,
    after JSONB,
    correlation_id UUID,
    request_id UUID,
    prev_hash CHAR(64),  -- hash of previous row
    row_hash CHAR(64) NOT NULL,  -- SHA256(timestamp + actor + action + resource + before + after + prev_hash)
    INDEX idx_audit_timestamp (timestamp),
    INDEX idx_audit_actor (actor_user_id, timestamp),
    INDEX idx_audit_resource (resource_type, resource_id, timestamp)
);
```

**Hash chain**: setiap row ter-link dengan hash row sebelumnya → tamper-evident. Verifikasi: jalankan `verify_audit_chain()` untuk pastikan tidak ada row di-modify.

### Event Ingestion

Audit service consume dari Kafka topic `ecommerce.audit.events`:

```json
{
  "event_id": "uuid",
  "occurred_at": "2026-06-21T10:00:00.123Z",
  "producer": "order-service",
  "action": "order.create",
  "actor": {
    "user_id": "uuid",
    "role": "buyer",
    "ip": "1.2.3.4"
  },
  "resource": {
    "type": "order",
    "id": "uuid",
    "before": null,
    "after": {"id":"uuid","status":"PENDING","total":150000}
  },
  "correlation_id": "uuid",
  "request_id": "uuid"
}
```

Service publish event ini setelah transaksi commit. Tidak publish = tidak di-audit. Sengaja dipilih pattern ini (bukan DB trigger) agar:
- Tidak lock DB table
- Bisa di-replay dari Kafka
- Async, tidak block business logic

### What Gets Audited

| Service | Actions Audited |
|---------|----------------|
| auth-service | user.register, user.login, user.logout, user.role_change, user.password_change, user.ban, token.refresh |
| catalog-service | product.create, product.update, product.price_change, product.delete, stock.adjust |
| order-service | cart.add, cart.remove, checkout.start, order.create, order.cancel, order.complete |
| payment-service | payment.charge, payment.succeed, payment.fail, payment.refund, withdrawal.request, withdrawal.approve |
| notification-service | (not audited directly, only via event log) |

---

## Error Tracking

### Error Capture

Setiap service punya SDK untuk catch error dan report ke audit-service:

**Python (auth/notification service)**:
```python
from shared.observability.error_reporter import report_error

try:
    risky_operation()
except Exception as e:
    report_error(
        error=e,
        context={"user_id": user_id, "action": "checkout"},
        request=request
    )
    raise  # re-raise setelah report
```

**Go (gateway/order/payment service)**:
```go
import "ecommerce/shared/observability"

defer func() {
    if r := recover(); r != nil {
        observability.ReportError(ctx, r, map[string]any{
            "user_id": userID,
            "action":  "checkout",
        })
        panic(r)
    }
}()
```

**Java (catalog service)**:
```java
@Aspect
@Component
public class ErrorTrackingAspect {
    @AfterThrowing(pointcut = "execution(* com.ecommerce.catalog..*(..))", throwing = "ex")
    public void trackError(JoinPoint joinPoint, Throwable ex) {
        ErrorReporter.report(ex, Map.of(
            "method", joinPoint.getSignature().getName(),
            "args", Arrays.toString(joinPoint.getArgs())
        ));
    }
}
```

### Error Storage

```sql
CREATE TABLE error_log (
    error_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    service VARCHAR(50) NOT NULL,
    environment VARCHAR(20) NOT NULL,  -- dev/staging/prod
    level VARCHAR(20) NOT NULL,  -- error/warning/fatal
    error_type VARCHAR(200),  -- exception class
    message TEXT,
    stack_trace TEXT,
    context JSONB,  -- user_id, request_id, dll
    request_id UUID,
    correlation_id UUID,
    user_id UUID,
    fingerprint CHAR(32),  -- MD5 of (service + error_type + sanitized stack) for grouping
    INDEX idx_error_timestamp (timestamp),
    INDEX idx_error_fingerprint (fingerprint, timestamp),
    INDEX idx_error_service (service, timestamp),
    INDEX idx_error_level (level, timestamp)
);
```

### Error Grouping

Error dengan fingerprint sama di-group jadi 1 issue. Fingerprint = MD5 dari:
- Service name
- Error type (exception class)
- Sanitized stack trace (file:line, function name — arg value disensor)

Tujuan: 1 bug = 1 issue, tidak terbelah karena user_id beda.

### Error Alerting

| Condition | Severity | Channel |
|-----------|----------|---------|
| Error rate > 5% in 5m | critical | PagerDuty + Slack #alert-critical |
| New error type muncul | warning | Slack #alert-warning |
| Error dari payment-service | critical | PagerDuty + Email oncall |
| PII terdeteksi di stack trace | critical | PagerDuty + auto-redact |
| Spike error (10x baseline) | warning | Slack #alert-warning |

---

## Anomaly Detection

### Real-time Rules

Jalankan di audit-service worker (consume dari `ecommerce.audit.events`):

| Rule | Action |
|------|--------|
| User register > 5x dalam 1 menit dari IP sama | Flag untuk review, throttle |
| Login failed > 10x dalam 5 menit dari IP sama | Block IP 1 jam |
| Payment refund > 5x dalam 1 jam dari 1 seller | Freeze seller, alert admin |
| Order dengan value > Rp 50 juta | Hold for manual review |
| Bulk product price change (>20% dalam 1 jam) | Alert admin |
| Withdrawal request > Rp 10 juta | Hold for manual review |
| Multiple login dari device berbeda negara dalam 1 jam | Force re-MFA |

### ML-based Detection (planned)

- **Isolation Forest** untuk anomali pada transaction pattern
- **Graph Neural Network** untuk deteksi fraud ring (multiple akun terhubung)
- **LSTM** untuk sequence anomaly (behavioral biometric)

---

## Compliance & Reporting

### Reports Available

1. **Daily audit summary** — count per action, top actors, anomalies
2. **User activity report** — full audit trail untuk user tertentu (GDPR/SOC2 request)
3. **Payment integrity report** — semua payment + refund + withdrawal dalam periode
4. **Access review report** — siapa akses data apa, untuk IAM review
5. **Incident timeline** — semua event dalam incident window untuk postmortem

### Data Retention

| Data type | Retention |
|-----------|-----------|
| Application log (Loki) | 30 hari |
| Audit log (PostgreSQL) | 7 tahun |
| Error log (PostgreSQL) | 90 hari (then archive to S3) |
| Metrics (Prometheus) | 90 hari (then long-term di Thanos) |
| Traces (Jaeger) | 7 hari |

### Access Control

- **Audit log**: superadmin only, dengan audit log of audit log access
- **Error log**: developer + admin, PII auto-redact
- **Metrics**: all internal user
- **Reports**: superadmin + compliance team

---

## Audit Verification

### Hash Chain Verification

Script `scripts/verify-audit-chain.py`:
```bash
python scripts/verify-audit-chain.py --from 2026-06-01 --to 2026-06-30
```

Verifikasi:
- `row_hash == SHA256(timestamp + actor + action + resource + before + after + prev_hash)`
- `prev_hash` row N == `row_hash` row N-1

Jika gagal → alert critical (audit log di-tamper).

### Daily Reconciliation

Cron job harian:
1. Hitung count event di Kafka (last 24h)
2. Hitung count row di audit_log (last 24h)
3. Jika selisih > 0.01% → alert (ada event hilang)

---

## Dashboard

### Grafana Dashboard

- **Audit overview**: event per menit, top action, top actor
- **Error overview**: error rate per service, top error, MTTR
- **Anomaly dashboard**: flagged events, manual review queue
- **Compliance dashboard**: audit completeness, retention status

URL: `http://grafana.localhost` (default credential di `.env`)

---

## Integration dengan Service

### Pattern yang digunakan

**Publish event setelah commit** (transactional outbox):

```python
# auth-service/app/services/user_service.py
async def register_user(data):
    async with db.transaction():
        user = await user_repo.create(data)
        await audit_repo.log({
            "action": "user.register",
            "actor": {"user_id": user.id, "ip": request.ip},
            "resource": {"type": "user", "id": user.id, "after": user.dict()}
        })
    # Kafka publish di luar transaction, dengan idempotency
    await kafka.publish("ecommerce.audit.events", event)
```

**Atau pakai transactional outbox pattern** (lebih robust):
```python
async with db.transaction():
    user = await user_repo.create(data)
    await outbox_repo.append({
        "topic": "ecommerce.audit.events",
        "payload": audit_event
    })
# Worker terpisah baca outbox, publish ke Kafka, hapus row
```

Pilihan terakhir dipakai untuk production — guarantee no event loss meski Kafka down saat commit.
