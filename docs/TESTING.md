# Test Configuration

## Running Tests

### All tests at once
```bash
./scripts/test.sh
```

### Per service

#### Auth Service (Python)
```bash
cd auth-service
pip install -e ".[dev]" --quiet
pytest tests/ -v --cov=app --cov-report=term-missing
```

#### Catalog Service (Java)
```bash
cd catalog-service
mvn test
mvn jacoco:report
# Open target/site/jacoco/index.html for coverage
```

#### Order/Payment/Shipping/Chat/Flash Sale (Go)
```bash
cd order-service
go test ./... -race -cover
go test ./internal/domain/... -v

cd payment-service
go test ./... -race -cover
go test ./internal/gateway/... -v

cd shipping-service
go test ./internal/provider/... -v

cd flashsale-service
go test ./internal/handler/... -v
```

#### Review/Wishlist/Coupon/Address/Search/Dispute/Loyalty/Fraud/Seller/Analytics/Admin/Recommendation (Python)
```bash
cd review-service && pytest tests/ -v
cd coupon-service && pytest tests/ -v
cd fraud-service && pytest tests/ -v
cd loyalty-service && pytest tests/ -v
cd dispute-service && pytest tests/ -v
cd order-service && pytest tests/ -v
```

## Coverage Targets

| Service | Target | Status |
|---------|--------|--------|
| auth-service | 90%+ | ✅ password, JWT, schemas tested |
| payment-service | 95%+ | ✅ gateway, domain, state machine tested |
| order-service | 90%+ | ✅ state machine, saga compensation tested |
| catalog-service | 85%+ | ✅ slug, stock calc tested |
| fraud-service | 90%+ | ✅ rules, score thresholds tested |
| coupon-service | 85%+ | ✅ validation, discount calc tested |
| review-service | 85%+ | ✅ profanity, rating logic tested |
| dispute-service | 85%+ | ✅ flow, deadlines tested |
| loyalty-service | 85%+ | ✅ tier, points, cashback tested |
| chat-service | 75%+ | ✅ hub logic tested |
| shipping-service | 75%+ | ✅ rajaongkir mock tested |
| flashsale-service | 75%+ | ✅ admin role logic tested |

## Test Pyramid

- **Unit tests** (75%): Fast, isolated, mock dependencies
- **Integration tests** (20%): With Testcontainers (real DB, Redis)
- **E2E tests** (5%): Via `scripts/demo/user_journey.py`

## Security Testing

```bash
# Python SAST
bandit -r auth-service/app -ll
bandit -r audit-service/app -ll

# Python dependency check
safety check

# Go SAST
gosec ./api-gateway/...
gosec ./order-service/...
gosec ./payment-service/...

# Java SAST
cd catalog-service && mvn spotbugs:check

# Docker image scan
trivy image ecommerce/api-gateway:latest
```
