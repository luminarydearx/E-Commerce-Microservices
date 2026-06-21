# Deployment Guide

## Local Development

### Prerequisites
- Docker 24+
- Docker Compose 2.20+
- OpenSSL 3+
- 8GB RAM (16GB recommended untuk full stack)
- 20GB disk space

### First-time Setup
```bash
git clone <repo-url>
cd ecommerce-microservices

cp .env.example .env
# Edit .env — ganti semua password "change_me_in_production"

./scripts/setup.sh
./scripts/migrate.sh
```

Setelah selesai, semua service akan jalan di:
- API Gateway: http://localhost:8080
- Auth: http://localhost:8001
- Catalog: http://localhost:8002
- Order: http://localhost:8003
- Payment: http://localhost:8004
- Notification: http://localhost:8005
- Audit: http://localhost:8006

Observability:
- Grafana: http://localhost:3001 (admin / dari .env)
- Prometheus: http://localhost:9090
- Jaeger: http://localhost:16686
- Kafka UI: http://localhost:8090

### Stop & Cleanup
```bash
# Stop services (data preserved)
docker-compose down

# Stop & delete volumes (FULL RESET)
docker-compose down -v
```

---

## Production Deployment

### Option 1: Docker Swarm

```bash
# Init swarm
docker swarm init

# Deploy
docker stack deploy -c docker-compose.prod.yml ecommerce

# Update
docker service update --image ecommerce/api-gateway:v2 ecommerce_api-gateway

# Scale
docker service scale ecommerce_api-gateway=5
```

### Option 2: Kubernetes (Recommended)

#### Setup
```bash
# Create namespace
kubectl create namespace ecommerce

# Apply configs
kubectl apply -f k8s/overlays/prod/

# Check rollout
kubectl rollout status deployment/api-gateway -n ecommerce
```

#### K8s manifests
Tersedia di `k8s/` directory:
- `base/` — deployment, service, configmap untuk setiap service
- `overlays/dev/` — dev-specific config (1 replica, no resource limits)
- `overlays/prod/` — prod config (3+ replicas, HPA, PDB, resource limits)

#### Helm chart (recommended)
```bash
helm repo add ecommerce https://charts.ecommerce.local
helm install ecommerce ecommerce/ecommerce \
  --namespace ecommerce \
  --create-namespace \
  --values values.prod.yaml
```

### Option 3: Cloud-managed (EKS/GKE/AKS)

Recommended architecture:
- **Compute**: EKS/GKE with Karpenter for auto-scaling
- **Database**: Amazon RDS / Cloud SQL (managed PostgreSQL with HA)
- **Cache**: Amazon ElastiCache / Memorystore (managed Redis)
- **Kafka**: Amazon MSK / Confluent Cloud (managed Kafka)
- **Search**: Amazon OpenSearch / Elastic Cloud
- **LB**: AWS ALB / GCP Load Balancer
- **CDN**: CloudFront / Cloud CDN untuk static assets & images
- **Secrets**: AWS Secrets Manager / Secret Manager
- **Monitoring**: CloudWatch + Grafana Cloud atau Datadog

---

## Production Checklist

### Security
- [ ] Generate fresh JWT RSA keypair (4096-bit), store in secret manager
- [ ] Set all passwords/secrets via secret manager (NOT env var)
- [ ] Enable mTLS antar service
- [ ] Configure WAF (Cloudflare/AWS WAF) di depan API Gateway
- [ ] Setup DDoS protection (Cloudflare/AWS Shield)
- [ ] Enable audit log retention policy (7 tahun)
- [ ] Pen-test sebelum go-live

### Database
- [ ] Enable connection pooling (PgBouncer atau RDS Proxy)
- [ ] Setup read replicas untuk catalog-service (read-heavy)
- [ ] Enable automated backup (point-in-time recovery, RPO < 5min)
- [ ] Test restore procedure
- [ ] Setup slow query log + alert
- [ ] Configure vacuum & analyze schedule

### Caching
- [ ] Redis cluster mode (minimum 3 master + 3 replica)
- [ ] Enable Redis persistence (AOF)
- [ ] Setup memory alert (>80%)
- [ ] Configure eviction policy per use-case

### Kafka
- [ ] Minimum 3 broker
- [ ] Replication factor 3
- [ ] min.insync.replicas 2
- [ ] Setup monitoring (Burrow untuk consumer lag)
- [ ] Configure retention per topic

### Observability
- [ ] Setup Grafana dashboard untuk setiap service
- [ ] Configure alerting (PagerDuty/Opsgenie)
- [ ] Enable distributed tracing (sample 10% di prod)
- [ ] Setup log aggregation (Loki/ELK)
- [ ] Configure uptime monitoring (external, e.g. Pingdom)

### Scaling
- [ ] HPA untuk setiap service (CPU > 70% → scale)
- [ ] KPA untuk Kafka consumer (based on lag)
- [ ] DB connection pool size = (max replicas * pool_size) ≤ max_connections
- [ ] Rate limit configured per endpoint
- [ ] CDN untuk static assets

### Disaster Recovery
- [ ] Document RTO/RPO target
- [ ] Multi-region deployment (active-passive)
- [ ] Test failover quarterly
- [ ] Document runbook untuk incident response

---

## CI/CD Pipeline

### GitHub Actions workflow

```yaml
# .github/workflows/ci.yml
name: CI/CD
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [auth-service, catalog-service, order-service, payment-service, notification-service, audit-service, api-gateway]
    steps:
      - uses: actions/checkout@v4
      - name: Test ${{ matrix.service }}
        run: ./scripts/test-service.sh ${{ matrix.service }}

  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: SAST
        run: |
          # Python
          pip install bandit safety
          bandit -r auth-service/app audit-service/app notification-service/app -ll
          safety check
          # Go
          go install github.com/securego/gosec/v2/cmd/gosec@latest
          gosec ./api-gateway/... ./order-service/... ./payment-service/...
          # Java
          mvn -f catalog-service/pom.xml spotbugs:check

  build-push:
    needs: [test, security-scan]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [api-gateway, auth-service, catalog-service, order-service, payment-service, notification-service, audit-service]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: ./${{ matrix.service }}
          push: true
          tags: ghcr.io/${{ github.repository }}/${{ matrix.service }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    needs: build-push
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to K8s
        run: |
          echo "${{ secrets.KUBE_CONFIG }}" > kubeconfig
          export KUBECONFIG=kubeconfig
          kubectl set image deployment/api-gateway \
            api-gateway=ghcr.io/${{ github.repository }}/api-gateway:${{ github.sha }} \
            -n ecommerce
          kubectl rollout status deployment/api-gateway -n ecommerce
```

---

## Blue-Green Deployment

Untuk zero-downtime deployment:

1. **Build new version** — push image dengan tag baru
2. **Deploy green** — create new deployment dengan tag baru, scale up
3. **Smoke test green** — health check + sample API call
4. **Switch traffic** — update service selector ke green
5. **Monitor** — observe error rate, latency for 10 menit
6. **Cleanup blue** — scale down old deployment
7. **Rollback if needed** — switch selector back to blue

```bash
# Deploy green
kubectl apply -f k8s/overlays/prod/api-gateway-green.yaml

# Wait for healthy
kubectl wait --for=condition=ready pod -l app=api-gateway,version=green -n ecommerce

# Switch service
kubectl patch service api-gateway -n ecommerce -p '{"spec":{"selector":{"version":"green"}}}'

# Watch
watch kubectl get pods -n ecommerce -l app=api-gateway
```

---

## Database Migration Strategy

### Strategy: Expand-then-Contract

1. **Expand** — add new column/table (backward compatible)
2. **Migrate** — deploy code yang pakai new schema (dual-write if needed)
3. **Contract** — drop old column setelah semua code pakai new schema

### Steps
```bash
# 1. Create migration
./scripts/create-migration.sh auth-service add_user_avatar_column

# 2. Apply migration (expand)
kubectl exec -it deploy/auth-service -n ecommerce -- alembic upgrade head

# 3. Deploy new code
kubectl set image deploy/auth-service auth-service=ghcr.io/.../auth-service:v2

# 4. Verify dual-write working
kubectl logs deploy/auth-service -n ecommerce | grep avatar

# 5. After 1 week, contract (drop old column)
./scripts/create-migration.sh auth-service drop_legacy_avatar
kubectl exec -it deploy/auth-service -n ecommerce -- alembic upgrade head
```

---

## Capacity Planning

### Development (current docker-compose)
- 1 instance per service
- 1 PostgreSQL, 1 Redis, 1 Kafka broker
- ~4GB RAM total
- Cukup untuk 100 RPS

### Staging
- 2 instance per service
- 1 PostgreSQL (small), 1 Redis, 3 Kafka broker
- ~16GB RAM
- Cukup untuk 1k RPS

### Production Small (startup)
- 3 instance per service kritis (gateway, auth, order, payment)
- 2 instance untuk service non-kritis (catalog, notification, audit)
- 1 PostgreSQL master + 2 replica (db.r5.large)
- 3 Redis node (cluster mode)
- 3 Kafka broker (m5.large)
- ~64GB RAM total
- Cukup untuk 10k RPS

### Production Large (Shopee-scale)
- 20+ instance API Gateway (autoscale)
- 10+ instance per service kritis
- Sharded PostgreSQL by user_id
- Redis cluster 6+ node
- Kafka 9 broker, 30+ partition
- Elasticsearch cluster 6+ node
- ~1TB RAM total
- Cukup untuk 100k+ RPS

---

## Monitoring & Alerting

### Uptime Monitoring
- External: Pingdom/UptimeRobot untuk endpoint public
- Internal: Blackbox exporter di Prometheus untuk internal endpoints

### Synthetic Monitoring
- Setup k6 script yang simulate user journey tiap 5 menit:
  1. Register
  2. Login
  3. Browse product
  4. Add to cart
  5. Checkout
  6. Payment
- Alert if p95 > 2s atau step gagal

### Alert Channels
- **Critical**: PagerDuty (call oncall engineer)
- **Warning**: Slack #alerts
- **Info**: Slack #alerts-info (digest daily)

### SLO Targets
- API Gateway availability: 99.95%
- API Gateway p95 latency: < 500ms
- Payment success rate: > 99.5%
- Order creation success rate: > 99.9%
- Audit log completeness: 100%

---

## Rollback Procedure

### Quick Rollback (within 5 min)
```bash
# K8s: rollback to previous version
kubectl rollout undo deployment/api-gateway -n ecommerce

# Verify
kubectl rollout status deployment/api-gateway -n ecommerce
```

### Database Rollback
```bash
# Alembic
kubectl exec -it deploy/auth-service -n ecommerce -- alembic downgrade -1

# Manual SQL (if no migration)
# 1. Restore from backup
pg_restore --dbname=auth_db --clean --if-exists /backup/auth_db_2026_06_21.dump
```

### Full Rollback (disaster)
1. Switch DNS ke DR region
2. Promote DR database ke primary
3. Scale up DR service
4. Investigate root cause di main region
