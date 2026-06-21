# Known Issues & Audit Log

> Catatan transparent tentang bug yang sudah diketahui, masalah yang sudah diperbaiki, dan hal yang perlu diperhatikan. File ini di-update setiap kali ada bug fix atau audit finding.

## Status Legend
- 🔴 **Critical** — bisa menyebabkan data loss, security breach, atau downtime
- 🟡 **Warning** — bisa menyebabkan unexpected behavior tapi tidak kritis
- 🟢 **Fixed** — sudah diperbaiki di versi terbaru
- ⚪ **Acknowledged** — diketahui, akan diperbaiki di versi mendatang

---

## 🔴 Critical Issues (Must Fix Before Production)

### 1. Internal Service Token Belum di-Rotate
- **Status**: ⚪ Acknowledged
- **Service**: All
- **Description**: `INTERNAL_TOKEN` antar service (order ↔ payment ↔ catalog) masih hardcoded di env. Tidak ada mekanisme rotasi otomatis.
- **Impact**: Jika token bocor, attacker bisa langsung call internal endpoints tanpa auth.
- **Mitigation**: 
  - [ ] Pindah ke mTLS dengan cert yang auto-rotate (90 hari)
  - [ ] Atau gunakan HashiCorp Vault dengan short-lived token
- **Workaround saat ini**: Restrict network access antar service (hanya pod yang sama yang bisa connect ke port internal)

### 2. JWT Key Rotation Belum Otomatis
- **Status**: ⚪ Acknowledged
- **Service**: auth-service, api-gateway, catalog-service
- **Description**: JWT signing key (`private.pem`) tidak di-rotate. Jika compromised, semua token harus di-revoke manual.
- **Impact**: Long-term compromise jika key bocor.
- **Mitigation**:
  - [ ] Implementasi key ID (kid) di JWT header untuk support multiple keys
  - [ ] Build key rotation endpoint (superadmin only)
  - [ ] Auto-rotate tiap 90 hari via cron + Vault

### 3. Database Backup Belum Otomatis
- **Status**: ⚪ Acknowledged
- **Service**: All
- **Description**: Belum ada cron job untuk backup PostgreSQL. Docker volume tidak ter-backup otomatis.
- **Impact**: Jika container corrupt/hilang, semua data hilang.
- **Mitigation**:
  - [ ] Setup pg_dump cron tiap 6 jam ke S3
  - [ ] Setup WAL archiving untuk point-in-time recovery
  - [ ] Test restore secara berkala

---

## 🟡 Warning Issues

### 4. Kafka Producer Tidak Idempotent di Audit Publisher
- **Status**: ⚪ Acknowledged
- **Service**: auth-service
- **File**: `app/services/kafka_publisher.py`
- **Description**: Jika Kafka down saat publish audit event, event hilang (best-effort only). Tidak ada retry queue.
- **Impact**: Audit log tidak lengkap, bisa miss compliance reporting.
- **Mitigation**:
  - [x] **Short-term**: Sudah di-log di aplikasi (cari "failed to publish audit event")
  - [ ] **Long-term**: Implement transactional outbox pattern — simpan event ke DB table dulu, worker terpisah publish ke Kafka dengan retry

### 5. Stock Reservation Tidak Auto-Expire di Background
- **Status**: ⚪ Acknowledged
- **Service**: catalog-service
- **Description**: Function `catalog.expire_reservations()` sudah ada di SQL, tapi belum ada scheduler yang memanggil.
- **Impact**: Stock bisa "reserved" terus jika user checkout tapi tidak bayar, jadi tidak available untuk user lain.
- **Mitigation**:
  - [ ] Setup cron job tiap 1 menit: `SELECT catalog.expire_reservations();`
  - [ ] Atau pakai pg_cron extension

### 6. Error Reporting dari Go Services Belum ke Audit-Service
- **Status**: ⚪ Acknowledged
- **Service**: api-gateway, order-service, payment-service
- **Description**: Python services punya pattern `report_error()` ke audit-service, tapi Go services belum implement.
- **Impact**: Error di Go service tidak ter-aggregate di audit-service, hilang dari error tracking dashboard.
- **Mitigation**:
  - [ ] Implement `pkg/observability/error_reporter.go` di Go services
  - [ ] Kirim via HTTP POST ke `audit-service:8006/api/v1/internal/errors`

### 7. Webhook Signature Verification Belum Implement
- **Status**: ⚪ Acknowledged
- **Service**: payment-service
- **Description**: Endpoint `/internal/webhooks/midtrans` dan `/internal/webhooks/xendit` belum verify signature.
- **Impact**: Attacker bisa forge webhook untuk mark payment as succeeded.
- **Mitigation**:
  - [x] **Penting**: Webhook endpoint hanya accessible via `X-Internal-Token` (InternalOnly middleware) — mitigasi sementara
  - [ ] **Real fix**: Verify HMAC signature dari Midtrans/Xendit menggunakan `WEBHOOK_SECRET`

---

## 🟢 Fixed Issues (Historical Record)

### F-001. Race Condition di Stock Reservation
- **Status**: 🟢 Fixed
- **Service**: catalog-service
- **Description**: Awalnya stock reservation pakai read-then-write (SELECT lalu UPDATE), menyebabkan double-booking saat concurrent checkout.
- **Fix**: Ganti ke atomic UPDATE dengan WHERE clause:
  ```sql
  UPDATE products SET reserved_stock = reserved_stock + $qty
  WHERE id = $1 AND stock - reserved_stock >= $qty
  ```
  Return rows_affected = 0 berarti gagal. Plus `SERIALIZABLE` isolation level.
- **Commit**: Initial implementation

### F-002. JWT Refresh Token Tidak di-Revoke Saat Rotation
- **Status**: 🟢 Fixed
- **Service**: auth-service
- **Description**: Saat refresh, token baru diterbitkan tapi token lama masih valid. User bisa pakai token lama untuk minta token baru lagi (infinite session).
- **Fix**: Revoke old refresh token sebelum issue new. Detect reuse: jika token revoked dipakai lagi → revoke ALL user tokens (signal of theft).
- **File**: `app/services/auth_service.py:refresh()`

### F-003. PII Bisa Muncul di Error Stack Trace
- **Status**: 🟢 Fixed
- **Service**: audit-service
- **Description**: Error dari service bisa contain email/phone/credit card di stack trace, lalu di-log ke audit-service.
- **Fix**: `redact_pii()` function di `audit-service/app/services/audit_ingest.py` yang auto-replace email, phone, credit card number dengan `[REDACTED_*]` sebelum save ke DB.
- **Marker**: `pii_redacted=true` di row yang sudah di-redact

### F-004. Account Lockout Bypass via Concurrent Login
- **Status**: 🟢 Fixed
- **Service**: auth-service
- **Description**: 5 concurrent login request bisa bypass `failed_login_attempts` counter karena race condition.
- **Fix**: `SERIALIZABLE` isolation di transaction + atomic UPDATE dengan `WHERE` clause:
  ```python
  await self.user_repo.increment_failed_login(user.id)
  # Internal: UPDATE users SET failed_login_attempts = failed_login_attempts + 1 WHERE id = $1
  ```
  Optimistic locking via `version` column juga di-aplikasikan.

### F-005. CORS Allowlist Tidak Dipakai (Wildcard)
- **Status**: 🟢 Fixed
- **Service**: All
- **Description**: Awalnya `Access-Control-Allow-Origin: *` — bisa di-exploit untuk CSRF jika token di-cookie.
- **Fix**: Allowlist explicit origins via `ALLOWED_ORIGINS` env var. Reflect origin only if in allowlist.

### F-006. SQL Injection Risk di Query Builder
- **Status**: 🟢 Fixed
- **Service**: catalog-service, order-service
- **Description**: Beberapa query builder awalnya concat string.
- **Fix**: 100% parameterized query:
  - Python: SQLAlchemy ORM with parameter binding
  - Go: pgx dengan `$1, $2` placeholders
  - Java: Spring Data JPA dengan `@Param` dan JPQL

### F-007. Idempotency Key Tidak Divalidasi Format
- **Status**: 🟢 Fixed
- **Service**: order-service, payment-service
- **Description**: Idempotency key bisa string apa saja, jadi attacker bisa generate key banyak untuk flood cache.
- **Fix**: Validate UUID format di middleware sebelum lookup Redis.

---

## ⚪ Acknowledged Limitations (Bukan Bug)

### L-001. Single Kafka Broker
- **Description**: docker-compose pakai 1 Kafka broker. Production harus minimal 3 broker untuk HA.
- **Impact**: Single point of failure untuk event bus.
- **Production fix**: Kafka cluster 3+ broker, replication factor 3, min ISR 2.

### L-002. Tidak Ada Search Service (Elasticsearch)
- **Description**: Product search masih pakai PostgreSQL `LIKE`/trigram. Tidak ada Elasticsearch.
- **Impact**: Search lambat untuk catalog besar (>1M products), tidak support typo-tolerance, autocomplete, faceted search.
- **Production fix**: Tambah search-service yang consume `product.created/updated` events dan index ke Elasticsearch.

### L-003. Tidak Ada ML-Based Fraud Detection
- **Description**: Fraud detection masih rule-based (audit-service).
- **Impact**: Pola fraud yang sophisticated tidak tertangkap.
- **Production fix**: Train model XGBoost/Isolation Forest dengan historical data, serve via Flask API.

### L-004. Tidak Ada CDN untuk Product Images
- **Description**: Images di-serve langsung dari origin server.
- **Impact**: Latency tinggi untuk user jauh dari server.
- **Production fix**: Cloudinary/CloudFront untuk image hosting.

### L-005. Logging Tidak Correlated dengan Traces di Beberapa Service
- **Description**: Go services belum inject `trace_id` ke log entries.
- **Impact**: Susah correlate log dengan trace di Jaeger.
- **Production fix**: Custom logrus hook yang inject `trace_id` dari context otomatis.

### L-006. Belum Implement Rate Limit per-Resource
- **Description**: Rate limit hanya per-IP dan per-user secara global.
- **Impact**: User bisa flood 1 endpoint kritis (e.g. checkout) sampai limit global.
- **Production fix**: Tambah per-endpoint rate limit config.

---

## Security Audit Findings

### A-001. Password Hashing sudah pakai Argon2id ✅
- Argon2id dengan memory cost 64MB, time cost 3, parallelism 4
- GPU-resistant, diakui oleh OWASP

### A-002. JWT pakai RS256 (asymmetric) ✅
- Private key hanya di auth-service
- Public key didistribusi ke gateway & service lain untuk verify
- Tidak ada shared secret

### A-003. Semua endpoint authenticated (kecuali public allowlist) ✅
- Login, register, forgot-password, public product list = public
- Lainnya wajib JWT via API Gateway

### A-004. SQL Injection mitigated ✅
- 100% parameterized query
- ORM dengan parameter binding
- SAST scan (bandit, gosec, spotbugs) di CI

### A-005. XSS mitigated ✅
- API return JSON, tidak render HTML
- CSP header set di API Gateway
- Output encoding di template email (Jinja2 autoescape)

### A-006. CSRF mitigated ✅
- API stateless, tidak pakai cookie
- Token di Authorization header (tidak auto-sent)
- CORS restrict ke allowlist

### A-007. SSRF mitigated ✅
- WAF rule block request ke private IP range
- Tidak ada endpoint yang fetch URL dari user input tanpa validation

### A-008. IDOR mitigated ✅
- Setiap query filter `WHERE user_id = ?`
- Authorization check di service layer

---

## Bug Reporting Process

Jika menemukan bug baru:

1. **Reproduce** — pastikan bug bisa di-reproduce consistently
2. **Document** — buat entry baru di file ini dengan format di atas
3. **Assess severity** — critical / warning / acknowledged
4. **Fix & test** — buat fix, write test yang verify fix
5. **Update file** — pindah entry ke "Fixed Issues" dengan commit reference

Untuk security vulnerability, kirim email ke security@ecommerce.local (jangan publish ke public repo sebelum fix).
