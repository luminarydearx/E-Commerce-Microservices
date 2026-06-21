# Architecture

## Design Principles

1. **Service Autonomy** — setiap service punya DB sendiri, tidak share schema
2. **Event-Driven** — komunikasi async via Kafka untuk decoupling
3. **API-First** — semua kontrak di-definisikan di proto/OpenAPI dulu
4. **Observability Built-in** — tracing, metrics, logs wajib dari hari 1
5. **Security by Default** — defense in depth, least privilege
6. **Idempotent** — semua operasi kritis aman di-retry
7. **Saga Pattern** — transaksi distributed dengan compensating action

---

## Service Decomposition

### Decision Matrix (mengapa bahasa X untuk service Y)

| Service | Bahasa | Alasan Teknis |
|---------|--------|---------------|
| **API Gateway** | Go | Goroutine ringan untuk reverse proxy ribuan koneksi; single binary; HTTP routing native cepat |
| **Auth Service** | Python | Library `python-jose`, `passlib`, `pyotp` matang; Mudah integrate OAuth2 provider; async I/O untuk verifikasi token |
| **Catalog Service** | Java | Spring Data JPA untuk query kompleks (filter, sort, facet); Hibernate batch processing untuk catalog besar; Elasticsearch client Spring resmi |
| **Order Service** | Go | State machine critical, latency rendah untuk checkout; goroutine untuk reservation timeout; type safety untuk order status enum |
| **Payment Service** | Go | Idempotency, saga pattern, high throughput; gRPC ke Midtrans/Xendit; concurrency safety untuk refund |
| **Notification Service** | Python | Jinja2 template; async worker dengan Celery; multi-channel (email, push, WA, in-app) |
| **Audit Service** | Python | Pandas untuk analisis error; async ingestion dari Kafka; alerting logic fleksibel |

---

## Communication Patterns

### Sync (gRPC)
Digunakan untuk: 
- Auth → API Gateway: token verification
- Order → Catalog: stock reservation (real-time)
- Payment → Order: payment status update

### Async (Kafka)
Digunakan untuk:
- `user.events` — registrasi, login, profil update
- `order.events` — cart update, checkout, status change
- `payment.events` — payment success, refund, withdrawal
- `audit.events` — semua event kritis untuk audit log
- `notification.events` — trigger email/push

### Topic Design
```
ecommerce.{aggregate}.{event_type}.{version}
```
Contoh:
- `ecommerce.user.registered.v1`
- `ecommerce.order.created.v1`
- `ecommerce.payment.succeeded.v1`

Setiap event wajib punya:
- `event_id` (UUID)
- `occurred_at` (ISO 8601 UTC)
- `producer` (service name)
- `correlation_id` (untuk trace)
- `payload` (event-specific)
- `version` (schema version)

---

## Data Ownership

| Data | Owner Service | Reader Services |
|------|---------------|-----------------|
| User credentials | auth-service | (nobody, via API only) |
| User profile | auth-service | catalog, order, payment (read-only via gRPC) |
| Product catalog | catalog-service | order, search (via gRPC/event) |
| Inventory | catalog-service | order (via gRPC for reservation) |
| Cart | order-service | catalog (read for price) |
| Order | order-service | payment, notification (via event) |
| Payment | payment-service | order (via gRPC for status) |
| Notification log | notification-service | audit (via event) |
| Audit log | audit-service | (nobody, append-only) |

**Aturan emas**: Service TIDAK boleh query DB service lain. Wajib via API (gRPC/REST) atau event.

---

## Transaction Safety

### Saga Pattern (untuk checkout flow)

```
[Checkout Saga]
1. Order Service: create order (status=PENDING)
2. Catalog Service: reserve stock           ──[fail]──▶ compensate: cancel order
3. Payment Service: charge payment          ──[fail]──▶ compensate: release stock, cancel order
4. Order Service: confirm order (status=CONFIRMED)
5. Notification Service: send confirmation  ──[fail]──▶ log for retry, don't fail saga
```

Setiap step punya compensating action. Jika gagal di tengah, saga coordinator jalankan compensation dalam urutan terbalik.

### Idempotency

Setiap endpoint POST/PUT yang mutate state finansial:
- Wajib terima header `Idempotency-Key: <uuid>`
- Server simpan `(key, request_hash, response)` di Redis 24 jam
- Request kedua dengan key sama → return cached response

### Database Transaction

- Order & Payment service: SERIALIZABLE isolation level untuk transaksi kritis
- Optimistic locking via `version` column untuk concurrent update
- Pessimistic locking (`SELECT FOR UPDATE`) untuk stock reservation

---

## Failure Handling

### Circuit Breaker
- Setiap outbound call (gRPC/HTTP) dibungkus circuit breaker
- Threshold: 5 failure / 10 detik → open 30 detik
- Half-open: 1 request test, sukses → closed, gagal → open lagi

### Retry with Backoff
- Max 3 retry dengan exponential backoff (1s, 2s, 4s)
- Hanya untuk idempotent operation
- Non-idempotent: gunakan idempotency key

### Dead Letter Queue (DLQ)
- Kafka consumer yang gagal 5x → push ke topic `ecommerce.dlq`
- Worker khusus process DLQ untuk manual intervention

### Graceful Shutdown
- SIGTERM → stop accept new request
- Wait in-flight request selesai (max 30s)
- Close DB pool, Kafka consumer
- Exit

---

## Security Architecture

### Defense in Depth

```
Layer 1: WAF (Cloudflare/Cloud Armor) — block SQLi, XSS pattern
Layer 2: API Gateway — rate limit, auth check, request size limit
Layer 3: Service — RBAC, input validation, business rule
Layer 4: Database — encryption at rest, row-level security, audit trigger
```

### Authentication Flow

```
1. Client POST /auth/login { email, password }
2. auth-service verify → return access_token (15min) + refresh_token (7d)
3. Client request dengan header: Authorization: Bearer <access_token>
4. API Gateway verify JWT → forward ke service + header X-User-Id, X-User-Roles
5. Service check RBAC → allow/deny
6. Jika access_token expired → client POST /auth/refresh { refresh_token }
```

### mTLS antar Service (production)

```
[Service A] ──TLS with client cert──▶ [Service B]
   │                                    │
   └── verify B's cert                  └── verify A's cert (signed by internal CA)
```

Self-signed CA internal, setiap service punya cert sendiri. Rotasi tiap 90 hari.

---

## Scalability

### Horizontal Scaling
- Setiap service stateless → scale with K8s HPA
- CPU > 70% → scale up
- RPS > threshold → scale up

### Database Scaling
- Read replica untuk read-heavy service (catalog)
- Sharding by user_id untuk order & payment (saat > 1M rows)
- Connection pooling (PgBouncer)

### Caching Strategy
- **L1**: In-memory cache (per instance, 60s TTL)
- **L2**: Redis (shared, 5min TTL)
- **L3**: Database (source of truth)

Cache invalidation: event-driven. Saat product update → publish event → consumer invalidate cache.

---

## Observability Architecture

### Three Pillars

1. **Logs** — structured JSON, correlation ID, push to Loki
2. **Metrics** — RED (Rate, Error, Duration) + custom business metrics, scrape by Prometheus
3. **Traces** — OpenTelemetry, sample 10% di production, 100% di dev

### Alerting

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Service down | health check fail > 1m | critical |
| High error rate | 5xx > 5% in 5m | critical |
| High latency | p95 > 1s in 5m | warning |
| DB connection pool exhausted | > 80% | critical |
| Kafka consumer lag | > 1000 messages | warning |
| Payment failure rate | > 10% in 5m | critical |
| Fraud pattern detected | any | critical |

---

## Disaster Recovery

- **RPO**: 5 menit (PostgreSQL streaming replication)
- **RTO**: 30 menit (automated failover)
- **Backup**: WAL archive setiap 5 menit, full backup harian, retain 30 hari
- **Multi-region**: active-passive (region utama + DR region)

---

## Capacity Planning (estimasi)

| Komponen | 1k RPS | 10k RPS | 100k RPS |
|----------|--------|---------|----------|
| API Gateway | 2 pod | 4 pod | 20 pod |
| Auth Service | 2 pod | 4 pod | 10 pod |
| Catalog Service | 2 pod | 6 pod | 30 pod |
| Order Service | 2 pod | 4 pod | 15 pod |
| Payment Service | 2 pod | 4 pod | 15 pod |
| PostgreSQL | 1 master + 2 replica | 1 master + 4 replica | sharded |
| Redis | 1 master + 1 replica | 3 master + 3 replica | cluster |
| Kafka | 3 broker | 5 broker | 9 broker |
