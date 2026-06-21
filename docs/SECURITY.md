# Security Model

## Threat Model (STRIDE)

| Threat | Mitigation |
|--------|------------|
| **S**poofing | JWT + refresh token rotation, mTLS antar service, password hashing Argon2id |
| **T**ampering | DB audit trigger, signed JWT (HS256/RS256), HMAC untuk webhook |
| **R**epudiation | Audit log immutable untuk semua transaksi kritis |
| **I**nformation Disclosure | Encryption at rest + in transit, RBAC, field-level encryption untuk PII |
| **D**enial of Service | Rate limit per IP/user, WAF, autoscaling, circuit breaker |
| **E**levation of Privilege | RBAC granular, principle of least privilege, no implicit allow |

---

## OWASP Top 10 Mitigation

### A01: Broken Access Control
- **JWT verification** di API Gateway untuk setiap request
- **RBAC** dengan permission per resource (`product:read`, `order:create`, `payment:refund`)
- **IDOR protection**: setiap query wajib filter `WHERE user_id = ?`
- **Audit log** untuk semua aksi sensitif

### A02: Cryptographic Failures
- **TLS 1.3** wajib untuk semua komunikasi
- **mTLS** antar service di production
- **Argon2id** untuk password hashing (memory-hard, anti-GPU)
- **AES-256-GCM** untuk encryption at rest
- **HMAC-SHA256** untuk signing webhook
- **No sensitive data in URL** (token via header, ID via path)

### A03: Injection
- **Parameterized query** 100% (SQLAlchemy ORM, JPA, sqlx)
- **Input validation** dengan Pydantic/Bean Validation
- **Output encoding** untuk semua user input yang dirender
- **SAST scan** otomatis di CI (bandit, gosec, spotbugs)

### A04: Insecure Design
- **Threat modeling** sebelum setiap fitur baru
- **Secure by default**: deny all, allow explicit
- **Fail secure**: error → deny, bukan allow
- **Rate limit** untuk semua endpoint

### A05: Security Misconfiguration
- **No default credentials**: semua service wajib env var
- **Error message** generic untuk user, detail hanya di log
- **Headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `CSP`, `HSTS`
- **No debug mode** di production

### A06: Vulnerable Components
- **Dependabot** aktif untuk semua repo
- **Snyk/Trivy** scan image Docker
- **Daily security audit** di CI
- **Patching SLA**: critical 24h, high 7d, medium 30d

### A07: Auth Failures
- **Account lockout** setelah 5 failed attempt (unlock via admin)
- **Password policy**: min 12 char, 1 upper, 1 lower, 1 digit, 1 symbol
- **MFA** wajib untuk seller & admin (TOTP via pyotp)
- **Session timeout**: access token 15min, refresh token 7d
- **Refresh token rotation**: setiap refresh → revoke old, issue new

### A08: Software/Data Integrity
- **Signed commits** wajib
- **Image signing** dengan Cosign
- **SBOM** generated per release
- **Reproducible build** untuk service kritis

### A09: Logging/Monitoring Failures
- **Centralized log** ke Loki (structured JSON)
- **Audit log** untuk semua transaksi finansial
- **Alerting** untuk pattern mencurigakan
- **Log retention**: app log 30d, audit log 7 tahun (compliance)

### A10: SSRF
- **Allowlist** untuk outbound HTTP request
- **Block private IP range** (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16)
- **DNS pinning** untuk prevent DNS rebinding
- **No redirect follow** untuk user-supplied URL

---

## Authentication & Authorization

### JWT Structure
```json
{
  "sub": "user_uuid",
  "iss": "auth-service",
  "aud": ["api-gateway", "order-service"],
  "roles": ["buyer"],
  "permissions": ["product:read", "order:create", "cart:write"],
  "exp": 1700000000,
  "iat": 1699999100,
  "jti": "token_uuid_for_revocation"
}
```

### Token Security
- **Signing**: RS256 (asymmetric, private key only di auth-service)
- **Lifetime**: access 15min, refresh 7d
- **Storage**: client-side HttpOnly Secure SameSite=Strict cookie (recommended)
- **Revocation**: JTI di Redis blacklist sampai exp
- **Rotation**: refresh → revoke old refresh, issue new pair

### RBAC Matrix

| Role | Permission |
|------|------------|
| `buyer` | `product:read`, `cart:write`, `order:create`, `review:write`, `profile:write:self` |
| `seller` | semua buyer + `product:write:own`, `order:read:own_product`, `withdrawal:request` |
| `admin` | semua seller + `user:read`, `user:write`, `product:write:all`, `payment:refund` |
| `superadmin` | semua admin + `config:write`, `audit:read` |

---

## Encryption

### At Rest
- **PostgreSQL**: pgcrypto untuk PII field (email, phone), TDE untuk volume
- **Redis**: tidak ada data sensitif (cache only)
- **Kafka**: TLS untuk transport, encryption untuk message sensitif
- **Backup**: AES-256-GCM

### In Transit
- **Client ↔ Gateway**: TLS 1.3 (HSTS, no downgrade)
- **Gateway ↔ Service**: mTLS dengan internal CA
- **Service ↔ Service**: mTLS
- **Service ↔ DB**: TLS
- **Service ↔ Kafka**: TLS + SASL SCRAM-SHA-512

### Key Management
- **Dev**: env var + sealed secrets
- **Production**: HashiCorp Vault dengan auto-rotation
- **Key rotation**: 90 hari untuk signing key, 30 hari untuk encryption key

---

## Rate Limiting

### Policy

| Endpoint type | Limit | Window | Burst |
|---------------|-------|--------|-------|
| Auth (login/register) | 5 | per minute | 10 |
| Public API (product list) | 100 | per minute | 200 |
| Authenticated API | 1000 | per minute | 1500 |
| Checkout/Payment | 10 | per minute | 20 |
| Admin API | 100 | per minute | 200 |

### Implementation
- **Algorithm**: token bucket (Redis-backed)
- **Key**: `{user_id}:{endpoint_type}` atau `{ip}:{endpoint_type}`
- **Response**: `429 Too Many Requests` + header `Retry-After` + `X-RateLimit-Remaining`

---

## Input Validation

### Layer
1. **API Gateway**: schema validation (OpenAPI), size limit (10MB), header check
2. **Service**: Pydantic/Bean Validation, business rule
3. **Database**: constraint, trigger

### Rule
- **String**: max length, charset allowlist, no null byte
- **Number**: range check, NaN/Infinity reject
- **Date**: range check (not future for birthdate)
- **Email**: RFC 5322 regex + DNS MX check
- **Phone**: E.164 format
- **URL**: allowlist host, block private IP

---

## Fraud Detection

### Rule-based (real-time)
- 3+ transaksi gagal dalam 10 menit → block 1 jam
- Login dari IP berbeda negara → trigger MFA
- Order > 10x nilai rata-rata user → manual review
- Multiple akun dari 1 device → flag

### ML-based (async)
- Model: Gradient Boosting (XGBoost) trained on historical fraud
- Feature: device fingerprint, behavioral pattern, graph anomaly
- Threshold: score > 0.7 → block, 0.4-0.7 → challenge (MFA/captcha)

---

## Audit Log

### What to log
- Semua aksi: **C**reate, **R**ead (sensitive), **U**pdate, **D**elete pada:
  - User (registrasi, login, role change, password change)
  - Order (create, status change, cancel)
  - Payment (charge, refund, withdrawal)
  - Product (price change, stock adjustment)
  - Admin action (config change, manual refund, user ban)

### Log structure
```json
{
  "audit_id": "uuid",
  "timestamp": "2026-06-21T10:00:00Z",
  "actor": {
    "user_id": "uuid",
    "role": "buyer",
    "ip": "1.2.3.4",
    "user_agent": "..."
  },
  "action": "order.create",
  "resource": {
    "type": "order",
    "id": "uuid"
  },
  "before": {},
  "after": {},
  "correlation_id": "uuid",
  "request_id": "uuid"
}
```

### Storage
- **Append-only** table dengan hash chain (blockchain-lite)
- Retention: 7 tahun (regulatory compliance)
- Access: superadmin only, dengan audit log of audit log access

---

## Incident Response

### Severity Level
- **P0**: data breach, payment system down → response 15 menit
- **P1**: partial outage, critical feature broken → response 1 jam
- **P2**: degraded performance, non-critical feature broken → response 4 jam
- **P3**: minor bug, cosmetic → response 1 hari

### Process
1. **Detect** — alert via PagerDuty/Opsgenie
2. **Acknowledge** — on-call engineer ack dalam SLA
3. **Investigate** — gather log, trace, metric
4. **Mitigate** — rollback / hotfix / rate limit
5. **Resolve** — root cause fix
6. **Postmortem** — blameless, dalam 48 jam, published to team

---

## Security Checklist (per service)

- [ ] Tidak ada hardcoded secret
- [ ] Tidak ada default password
- [ ] Tidak ada `debug=true` di production config
- [ ] Semua endpoint authenticated (kecuali public allowlist)
- [ ] Input validation di setiap layer
- [ ] Parameterized query 100%
- [ ] Rate limit aktif
- [ ] Log tidak mengandung PII/sensitive data
- [ ] Error message generic ke user, detail ke log
- [ ] Dependency terbaru (no known CVE)
- [ ] Container run as non-root
- [ ] Container image scanned (Trivy)
- [ ] Security headers set
- [ ] CORS configured (no `*`)
- [ ] TLS 1.2+ only
- [ ] mTLS untuk service-to-service
- [ ] Audit log untuk aksi kritis
- [ ] Health check endpoint (no sensitive info)
- [ ] Graceful shutdown
- [ ] Resource limit (CPU/memory) di container
