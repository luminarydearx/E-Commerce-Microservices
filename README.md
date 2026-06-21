# 🛒 E-Commerce Microservices Platform

> **A production-grade, scalable e-commerce backend** — built to handle Shopee/Tokopedia-scale traffic.
> Hybrid polyglot microservices (Go + Java + Python), event-driven, secure-by-default, fully observable.

[![Architecture](https://img.shields.io/badge/architecture-microservices-blue?style=flat-square)](docs/ARCHITECTURE.md)
[![Services](https://img.shields.io/badge/services-20%20microservices-green?style=flat-square)](#-services)
[![Languages](https://img.shields.io/badge/languages-Go%20%7C%20Java%20%7C%20Python-orange?style=flat-square)](#-tech-stack)
[![Security](https://img.shields.io/badge/security-OWASP%20Top%2010-red?style=flat-square)](docs/SECURITY.md)
[![License](https://img.shields.io/badge/license-MIT-brightgreen?style=flat-square)](LICENSE)

---

## 📖 Table of Contents

- [🎯 Project Overview](#-project-overview)
- [✨ Key Features](#-key-features)
- [🏗 Architecture](#-architecture)
- [🛠 Tech Stack](#-tech-stack)
- [📦 Services](#-services)
- [🔒 Security](#-security)
- [📊 Observability](#-observability)
- [🚀 Quick Start](#-quick-start)
- [📚 Documentation](#-documentation)
- [🧪 Testing](#-testing)
- [🚢 Deployment](#-deployment)
- [📈 Roadmap](#-roadmap)
- [🤝 Contributing](#-contributing)

---

## 🎯 Project Overview

This is a **complete e-commerce backend platform** architected for **massive scale** (target: 100k+ RPS) and **zero-downtime operation**. It's not a toy project — every service is designed with production-grade concerns in mind: security, observability, fault tolerance, and audit compliance.

### What Makes This Special

- **20 microservices** in 3 programming languages, each chosen for its sweet spot
- **Event-driven architecture** with Kafka as the backbone
- **Tamper-evident audit log** with hash chain (blockchain-lite) for compliance
- **Real-time fraud detection** with rule-based + ML-ready scoring
- **Saga pattern** for distributed transactions across order → catalog → payment
- **Atomic stock reservation** via Redis Lua scripts (flash sale ready)
- **End-to-end observability** — every request is traceable across services
- **Security by default** — OWASP Top 10 mitigated, MFA, RBAC, PII auto-redaction

### Why Hybrid Polyglot?

Different problems need different tools. We don't force one language for everything:

| Service | Language | Why |
|---------|----------|-----|
| API Gateway, Order, Payment, Flash Sale, Chat | **Go** | Goroutines for concurrency, low latency, single binary |
| Catalog | **Java/Spring Boot** | Mature ORM for complex queries, Hibernate batch processing |
| Auth, Notification, Audit, Review, Wishlist, Coupon, Address, Search, Dispute, Loyalty, Fraud, Seller, Analytics, Admin, Recommendation | **Python/FastAPI** | Fast development, rich ecosystem for ML/data, async I/O |

---

## ✨ Key Features

### 🛍 E-Commerce Core
- ✅ User authentication with JWT RS256 + MFA (TOTP)
- ✅ Product catalog with category, variant, image gallery
- ✅ Shopping cart with price snapshot & 7-day expiry
- ✅ Checkout saga (reserve stock → create order → process payment)
- ✅ Order state machine (PENDING → PAID → CONFIRMED → SHIPPED → DELIVERED → COMPLETED)
- ✅ Multi-provider payment (Midtrans, Xendit) with idempotency
- ✅ Withdrawal system for sellers

### 🎁 Growth & Engagement
- ✅ Review & rating system (1-5 stars, photos, helpful votes, seller responses)
- ✅ Wishlist with price drop alerts & restock notifications
- ✅ Coupon/voucher system (percentage, fixed, free shipping, stackable rules)
- ✅ Loyalty program (Silver/Gold/Platinum/Diamond tiers, points, cashback, rewards)
- ✅ Flash sale with queue system & atomic stock deduction (anti-bot)
- ✅ Live chat (WebSocket) between buyer ↔ seller
- ✅ Personalized recommendations (collaborative filtering, frequently bought together)

### 🚚 Operations
- ✅ Multi-courier shipping (JNE, TIKI, POS, SiCepat, J&T) via RajaOngkir
- ✅ Real-time shipment tracking
- ✅ Dispute & refund workflow with admin mediation
- ✅ Multi-address management with geocoding
- ✅ Seller dashboard with sales analytics & trust badge
- ✅ Admin aggregator service for unified management

### 🛡 Trust & Safety
- ✅ Fraud detection (rule-based + ML-ready) with auto-block IP/user
- ✅ Account lockout after 5 failed login attempts
- ✅ Velocity checks (transactions per minute/hour/day)
- ✅ PII auto-redaction in logs & errors
- ✅ Centralized audit log with hash chain (tamper-evident)
- ✅ Anomaly detection (multiple registrations, refund spikes, large orders)

### 🔍 Search & Discovery
- ✅ Elasticsearch-powered full-text search with Indonesian analyzer
- ✅ Autocomplete with fuzzy matching (typo tolerance)
- ✅ Faceted search (categories, price ranges)
- ✅ Search result caching (5 min Redis)

### 📊 Analytics & BI
- ✅ Real-time dashboard (active users, orders, revenue, WS connections)
- ✅ Conversion funnel (view → cart → checkout → paid → delivered)
- ✅ Cohort retention analysis
- ✅ Top products / top sellers reports
- ✅ Custom event tracking from frontend

---

## 🏗 Architecture

```
                          ┌─────────────────────────────┐
                          │   Client (Web / Mobile)     │
                          └─────────────┬───────────────┘
                                        │ HTTPS (TLS 1.3)
                                        ▼
                          ┌─────────────────────────────┐
                          │   API Gateway (Go)          │
                          │  • JWT verification         │
                          │  • Rate limiting (Redis)    │
                          │  • WAF (SQLi/XSS/SSRF)      │
                          │  • Idempotency enforcement  │
                          │  • Request routing          │
                          └─────────────┬───────────────┘
                                        │
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
  ┌──────────┐  ┌───────────┐   ┌───────────┐   ┌───────────┐  ┌───────────┐
  │ Auth Svc │  │ Catalog   │   │ Order Svc │   │ Payment   │  │ Notif Svc │
  │ (Python) │  │ (Java)    │   │ (Go)      │   │ Svc (Go)  │  │ (Python)  │
  └────┬─────┘  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘  └─────┬─────┘
       │              │               │               │              │
       │              │               │               │              │
       ▼              ▼               ▼               ▼              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                    Event Bus (Apache Kafka)                          │
  │  topics: user.events, order.events, payment.events, audit.events     │
  └──────────────────────────────────────────────────────────────────────┘
       │                                                              │
       ▼                                                              ▼
  ┌──────────┐                                                  ┌───────────┐
  │ Audit Svc│◄──── Error Reports (all services)               │  Search   │
  │ (Python) │                                                  │  (ES)     │
  └──────────┘                                                  └───────────┘

  + 13 more services: Review, Wishlist, Coupon, Shipping, Address,
    Dispute, Chat, Flash Sale, Loyalty, Fraud, Seller, Analytics,
    Admin, Recommendation

  Observability Stack:
  • Prometheus + Grafana (metrics)
  • Loki + Promtail (logs)
  • Jaeger + OpenTelemetry (distributed tracing)
  • Custom Audit Service (error tracking + audit log)
```

### Design Principles

1. **Service Autonomy** — each service owns its data, no shared schema
2. **Event-Driven** — async communication via Kafka for decoupling
3. **API-First** — contracts defined in OpenAPI/proto before implementation
4. **Observability Built-in** — tracing, metrics, logs mandatory from day 1
5. **Security by Default** — defense in depth, least privilege, fail-secure
6. **Idempotency** — all critical operations safe to retry
7. **Saga Pattern** — distributed transactions with compensating actions

📖 **Deep dive**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 🛠 Tech Stack

### Backend Services
| Language | Framework | Use Case |
|----------|-----------|----------|
| **Go 1.22** | Gin | API Gateway, Order, Payment, Shipping, Chat, Flash Sale |
| **Java 21** | Spring Boot 3 | Catalog Service |
| **Python 3.11** | FastAPI | Auth, Notification, Audit, Review, Wishlist, Coupon, Address, Search, Dispute, Loyalty, Fraud, Seller, Analytics, Admin, Recommendation |

### Data Stores
- **PostgreSQL 16** — primary OLTP database (per-service database isolation)
- **Redis 7** — cache, rate limiting, idempotency, session, queue
- **Elasticsearch 8** — product search & log indexing
- **Apache Kafka** — event streaming backbone

### Observability
- **OpenTelemetry** — distributed tracing (instrumented in every service)
- **Jaeger** — trace visualization
- **Prometheus** — metrics scraping (RED method)
- **Grafana** — dashboards (pre-built)
- **Loki + Promtail** — structured log aggregation

### Infrastructure
- **Docker + Docker Compose** — local development & testing
- **Kubernetes** — production deployment (manifests provided)
- **Helm** — packaged K8s deployment (planned)
- **Terraform** — IaC for cloud provisioning (planned)

### Security
- **Argon2id** — password hashing (memory-hard, GPU-resistant)
- **JWT RS256** — asymmetric token signing
- **TOTP (RFC 6238)** — MFA via pyotp
- **Redis Lua Scripts** — atomic operations (stock deduction, rate limit)

---

## 📦 Services

20 microservices, each with its own database, deployed independently:

### Core Services
| # | Service | Lang | Port | Responsibility |
|---|---------|------|------|----------------|
| 1 | **api-gateway** | Go | 8080 | Reverse proxy, auth, rate limit, WAF |
| 2 | **auth-service** | Python | 8001 | JWT, RBAC, MFA, refresh token rotation |
| 3 | **catalog-service** | Java | 8002 | Product, category, inventory, stock reservation |
| 4 | **order-service** | Go | 8003 | Cart, checkout saga, order state machine |
| 5 | **payment-service** | Go | 8004 | Payment, refund, withdrawal (Midtrans/Xendit) |
| 6 | **notification-service** | Python | 8005 | Email, push, in-app (Kafka consumer) |
| 7 | **audit-service** | Python | 8006 | Centralized audit log + error tracking |

### Feature Services
| # | Service | Lang | Port | Responsibility |
|---|---------|------|------|----------------|
| 8 | **review-service** | Python | 8007 | Product reviews, ratings, helpful votes |
| 9 | **wishlist-service** | Python | 8008 | Save products, price drop alerts |
| 10 | **coupon-service** | Python | 8009 | Vouchers, discounts, redemption limits |
| 11 | **shipping-service** | Go | 8010 | Multi-courier shipping (RajaOngkir) |
| 12 | **address-service** | Python | 8011 | Multi-address, geocoding |
| 13 | **search-service** | Python | 8012 | Elasticsearch full-text search |
| 14 | **dispute-service** | Python | 8013 | Buyer-seller dispute resolution |
| 15 | **chat-service** | Go | 8014 | WebSocket real-time chat |
| 16 | **flashsale-service** | Go | 8015 | Flash sale with queue system |
| 17 | **loyalty-service** | Python | 8016 | Points, tiers, cashback, rewards |
| 18 | **fraud-service** | Python | 8017 | Fraud detection, IP/user blocking |
| 19 | **seller-service** | Python | 8018 | Seller dashboard, trust badge |
| 20 | **analytics-service** | Python | 8019 | BI dashboard, funnel, cohort |
| | **admin-service** | Python | 8020 | Admin aggregator (proxy) |
| | **recommendation-service** | Python | 8021 | ML-based recommendations |

---

## 🔒 Security

This project takes security seriously. Every layer has defense-in-depth:

### OWASP Top 10 Mitigation

| Threat | Mitigation |
|--------|------------|
| **A01 Broken Access Control** | JWT + RBAC + IDOR protection (filter `WHERE user_id = ?`) |
| **A02 Cryptographic Failures** | TLS 1.3, Argon2id, AES-256-GCM at rest, RS256 JWT |
| **A03 Injection** | 100% parameterized queries, ORM, SAST scan in CI |
| **A04 Insecure Design** | Threat modeling, secure-by-default, fail-secure |
| **A05 Security Misconfiguration** | No default credentials, generic error messages |
| **A06 Vulnerable Components** | Dependabot, Snyk, Trivy image scan |
| **A07 Auth Failures** | Account lockout, MFA, refresh token rotation with reuse detection |
| **A08 Integrity Failures** | Signed commits, image signing (Cosign), SBOM |
| **A09 Logging Failures** | Centralized audit log, immutable (hash chain), 7-year retention |
| **A10 SSRF** | WAF rules block private IP ranges, allowlist for outbound HTTP |

### Authentication & Authorization
- **JWT RS256** (asymmetric) — private key only in auth-service
- **Refresh token rotation** — revoke old on refresh, detect reuse → revoke ALL
- **MFA TOTP** — RFC 6238, optional but enforced for seller/admin
- **RBAC** — granular permissions per resource (`product:write:own`, `payment:refund`, etc)
- **Account lockout** — 5 failed attempts → 30 min lock

### Fraud Detection
- **Rule-based** (real-time): velocity checks, blocked IP/user, large order flags
- **ML-ready** (planned): XGBoost + Isolation Forest for anomaly detection
- **Auto-block IP** — fraud score ≥ 0.7 → IP blocked 1 hour
- **Challenge MFA** — score 0.4-0.7 → require MFA/CAPTCHA

### Audit Log
- **Hash chain** (blockchain-lite) — tamper-evident, broken chain = alert
- **PII auto-redaction** — email, phone, credit card masked before storage
- **7-year retention** — regulatory compliance ready
- **Verification endpoint** — `GET /admin/audit/verify` to check integrity

📖 **Deep dive**: [docs/SECURITY.md](docs/SECURITY.md), [docs/AUDIT.md](docs/AUDIT.md), [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)

---

## 📊 Observability

Three pillars of observability, all built-in:

### 1. Logs (Structured JSON)
```json
{
  "timestamp": "2026-06-21T10:00:00.123Z",
  "level": "info",
  "service": "order-service",
  "message": "request completed",
  "method": "POST",
  "path": "/api/v1/checkout",
  "status": 201,
  "duration_ms": 234,
  "request_id": "uuid",
  "correlation_id": "uuid",
  "user_id": "uuid"
}
```

Aggregated in **Loki**, queryable via LogQL in Grafana.

### 2. Metrics (Prometheus)
- **RED method** (Rate, Errors, Duration) per endpoint
- Custom business metrics: orders created, payments succeeded, fraud flags
- Pre-built Grafana dashboards

### 3. Traces (OpenTelemetry + Jaeger)
- Every request gets `trace_id` & `span_id`
- Propagated across services via `traceparent` header
- DB queries, Redis ops, HTTP calls all instrumented
- Sample 100% in dev, 10% in prod

### Alerting
| Alert | Threshold | Severity |
|-------|-----------|----------|
| Service down | health check fail > 1m | critical |
| High error rate | 5xx > 5% in 5m | critical |
| High latency | p95 > 1s in 5m | warning |
| Payment failure rate | > 10% in 5m | critical |
| Fraud score ≥ 0.7 | any | critical |
| Audit chain broken | any | critical |

---

## 🚀 Quick Start

### Prerequisites
- Docker 24+
- Docker Compose 2.20+
- 16GB RAM (recommended for full stack)
- 20GB disk space

### One-Command Setup

```bash
git clone <repo-url>
cd ecommerce-microservices
cp .env.example .env

# Generate JWT RSA keypair (4096-bit)
./scripts/gen-certs.sh ./keys

# Start everything
docker-compose up -d

# Run database migrations
./scripts/migrate.sh
```

### Verify

```bash
# API Gateway health
curl http://localhost:8080/health

# Register a user
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "email": "test@example.com",
    "password": "StrongP@ss123!",
    "role": "buyer"
  }'

# Browse products
curl http://localhost:8080/api/v1/products
```

### Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| API Gateway | http://localhost:8080 | - |
| Auth Service | http://localhost:8001 | - |
| Catalog Service | http://localhost:8002 | - |
| Order Service | http://localhost:8003 | - |
| Payment Service | http://localhost:8004 | - |
| Notification | http://localhost:8005 | - |
| Audit Service | http://localhost:8006 | - |
| Review Service | http://localhost:8007 | - |
| Wishlist | http://localhost:8008 | - |
| Coupon | http://localhost:8009 | - |
| Shipping | http://localhost:8010 | - |
| Address | http://localhost:8011 | - |
| Search | http://localhost:8012 | - |
| Dispute | http://localhost:8013 | - |
| Chat (WebSocket) | ws://localhost:8014 | - |
| Flash Sale | http://localhost:8015 | - |
| Loyalty | http://localhost:8016 | - |
| Fraud | http://localhost:8017 | - |
| Seller | http://localhost:8018 | - |
| Analytics | http://localhost:8019 | - |
| Admin | http://localhost:8020 | - |
| Recommendation | http://localhost:8021 | - |

### Observability URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3001 | admin / from .env |
| Prometheus | http://localhost:9090 | - |
| Jaeger | http://localhost:16686 | - |
| Loki | http://localhost:3100 | - |
| Kafka UI | http://localhost:8090 | - |
| Elasticsearch | http://localhost:9200 | - |

---

## 📚 Documentation

Comprehensive documentation in `docs/`:

### Architecture & Design
- 📐 [ARCHITECTURE.md](docs/ARCHITECTURE.md) — service decomposition, communication patterns, data ownership
- 🔒 [SECURITY.md](docs/SECURITY.md) — threat model, OWASP mitigation, RBAC matrix
- 🛡 [AUDIT.md](docs/AUDIT.md) — audit log, error tracking, anomaly detection
- 🚢 [DEPLOY.md](docs/DEPLOY.md) — production deployment, K8s, capacity planning
- 🧪 [TESTING.md](docs/TESTING.md) — testing strategy, coverage targets
- ⚠️ [KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) — known issues, audit findings, fix history

### API Reference (per service)
Located in `docs/api/`:

| API Doc | Service |
|---------|---------|
| [users.md](docs/api/users.md) | Auth Service |
| [products.md](docs/api/products.md) | Catalog Service |
| [cart.md](docs/api/cart.md) | Order Service |
| [orders.md](docs/api/orders.md) | Order Service |
| [payments.md](docs/api/payments.md) | Payment Service |
| [reviews.md](docs/api/reviews.md) | Review Service |
| [wishlist.md](docs/api/wishlist.md) | Wishlist Service |
| [coupons.md](docs/api/coupons.md) | Coupon Service |
| [shipping.md](docs/api/shipping.md) | Shipping Service |
| [addresses.md](docs/api/addresses.md) | Address Service |
| [search.md](docs/api/search.md) | Search Service |
| [disputes.md](docs/api/disputes.md) | Dispute Service |
| [chat.md](docs/api/chat.md) | Chat Service |
| [flashsale.md](docs/api/flashsale.md) | Flash Sale Service |
| [loyalty.md](docs/api/loyalty.md) | Loyalty Service |
| [fraud.md](docs/api/fraud.md) | Fraud Service |
| [seller.md](docs/api/seller.md) | Seller Service |
| [analytics.md](docs/api/analytics.md) | Analytics Service |
| [admin.md](docs/api/admin.md) | Admin Service |
| [recommendations.md](docs/api/recommendations.md) | Recommendation Service |
| [notifications.md](docs/api/notifications.md) | Notification Service |
| [audit.md](docs/api/audit.md) | Audit Service |

---

## 🧪 Testing

### Testing Pyramid

```
        /\
       /E2E\           5% — Critical user journeys
      /------\
     /Integ.  \       20% — Service-to-service (Testcontainers)
    /----------\
   /   Unit     \     75% — Business logic
  /--------------\
```

### Coverage Targets

| Service | Unit | Integration |
|---------|------|-------------|
| auth-service | 90%+ | 80%+ |
| payment-service | 95%+ | 90%+ |
| order-service | 90%+ | 80%+ |
| catalog-service | 85%+ | 75%+ |
| Other services | 75%+ | 50%+ |

### Security Scanning
- **Bandit** (Python SAST)
- **gosec** (Go SAST)
- **SpotBugs** (Java SAST)
- **Safety** (Python dependency scan)
- **Trivy** (Docker image scan)

### Run Tests

```bash
# All tests + security scans
./scripts/test.sh

# Single service
cd auth-service && pytest tests/ --cov=app
cd order-service && go test ./... -race -cover
cd catalog-service && mvn test
```

📖 **Deep dive**: [docs/TESTING.md](docs/TESTING.md)

---

## 🚢 Deployment

### Local Development
```bash
docker-compose up -d
```

### Production (Kubernetes)
```bash
kubectl apply -f k8s/overlays/prod/
kubectl rollout status deployment/api-gateway -n ecommerce
```

### Capacity Planning

| Component | 1k RPS | 10k RPS | 100k RPS |
|-----------|--------|---------|----------|
| API Gateway | 2 pods | 4 pods | 20 pods |
| Auth Service | 2 pods | 4 pods | 10 pods |
| Catalog Service | 2 pods | 6 pods | 30 pods |
| Order/Payment | 2 pods | 4 pods | 15 pods |
| PostgreSQL | 1 master + 2 replica | 1 + 4 replica | sharded |
| Redis | 1 + 1 replica | 3 + 3 cluster | cluster |
| Kafka | 3 broker | 5 broker | 9 broker |

### Disaster Recovery
- **RPO**: 5 minutes (PostgreSQL streaming replication)
- **RTO**: 30 minutes (automated failover)
- **Backup**: WAL archive every 5 min, full daily, retain 30 days
- **Multi-region**: active-passive (primary + DR region)

📖 **Deep dive**: [docs/DEPLOY.md](docs/DEPLOY.md)

---

## 📈 Roadmap

### Phase 1 (Q3 2026) — Current
- ✅ All 20 microservices with full feature set
- ✅ Observability stack (Prometheus, Grafana, Jaeger, Loki)
- ✅ Audit log with hash chain
- ✅ Fraud detection (rule-based)
- ⏳ ML-based fraud detection (XGBoost training pipeline)
- ⏳ Helm charts for production K8s deployment
- ⏳ Multi-region deployment guide

### Phase 2 (Q4 2026) — Scale
- 🔲 B2B / wholesale module
- 🔲 Multi-currency & international shipping
- 🔲 Live streaming commerce
- 🔲 Group buy / team buy
- 🔲 Pre-order system
- 🔲 Dropshipping API

### Phase 3 (Q1 2027) — Intelligence
- 🔲 Real ML recommendation (Neural Collaborative Filtering)
- 🔲 Computer vision for product image moderation
- 🔲 NLP for review sentiment analysis
- 🔲 Chatbot for customer service
- 🔲 Dynamic pricing engine
- 🔲 Inventory forecasting

---

## 🤝 Contributing

### Development Setup

1. Fork & clone the repository
2. Run `./scripts/setup.sh` for first-time setup
3. Make changes in feature branch
4. Run `./scripts/test.sh` — all tests must pass
5. Submit PR with description & test coverage

### Code Style

- **Go**: `gofmt` + `golint`, follow [Effective Go](https://go.dev/doc/effective_go)
- **Java**: Google Java Style Guide, Lombok allowed
- **Python**: `ruff` (PEP 8 + isort), `mypy` strict mode

### Commit Convention

```
feat(service): add flash sale queue system

- Implement Redis-backed queue with position tracking
- Add atomic stock deduction via Lua script
- Add purchase token with 5-min TTL

Closes #123
```

### Pull Request Checklist

- [ ] Tests added/updated (coverage not decreased)
- [ ] Documentation updated (API docs, README if needed)
- [ ] Security implications considered
- [ ] No secrets/credentials in code
- [ ] CI passes (lint, test, security scan)
- [ ] BREAKING changes documented

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

Free for commercial use. Attribution appreciated but not required.

---

## 🙏 Acknowledgments

Built with these amazing open-source projects:

- [FastAPI](https://fastapi.tiangolo.com/) — Python async web framework
- [Spring Boot](https://spring.io/projects/spring-boot) — Java application framework
- [Gin](https://gin-gonic.com/) — Go HTTP web framework
- [PostgreSQL](https://www.postgresql.org/) — world's most advanced open-source database
- [Redis](https://redis.io/) — in-memory data structure store
- [Apache Kafka](https://kafka.apache.org/) — distributed event streaming platform
- [Elasticsearch](https://www.elastic.co/elasticsearch/) — search & analytics engine
- [OpenTelemetry](https://opentelemetry.io/) — observability framework
- [Prometheus](https://prometheus.io/) — monitoring & alerting
- [Grafana](https://grafana.com/) — analytics & visualization
- [Docker](https://www.docker.com/) — containerization platform

---

## ⭐ Show Your Support

If this project helped you or inspired you, please consider:
- ⭐ Starring the repository
- 🐛 Reporting bugs via Issues
- 💡 Suggesting features via Discussions
- 📢 Sharing with your network

---

<p align="center">
  <strong>Built with ❤️ for the Indonesian e-commerce community</strong>
</p>

<p align="center">
  <sub>Ready to scale to millions of users. Ready for your next Shopee/Tokopedia.</sub>
</p>
