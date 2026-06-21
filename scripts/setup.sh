#!/bin/bash
# Setup script - run after fresh clone
set -e

echo "============================================="
echo "E-Commerce Microservices - Setup"
echo "============================================="

# Check prerequisites
echo ""
echo "[1/5] Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "Docker is required. Install: https://docs.docker.com/get-docker/"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "docker-compose is required."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "openssl is required."; exit 1; }
echo "  ✓ All prerequisites met"

# Copy env file
echo ""
echo "[2/5] Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ✓ Created .env from .env.example"
    echo "  ⚠ Edit .env to change default passwords before production!"
else
    echo "  ✓ .env already exists"
fi

# Generate JWT keys
echo ""
echo "[3/5] Generating JWT RSA keypair..."
chmod +x scripts/gen-certs.sh
./scripts/gen-certs.sh ./keys

# Create directories
echo ""
echo "[4/5] Creating directories..."
mkdir -p download logs
echo "  ✓ Created download/ and logs/"

# Build & start services
echo ""
echo "[5/5] Building and starting services..."
echo "  (This may take 5-10 minutes on first run)"
docker-compose build
docker-compose up -d

# Wait for services to be healthy
echo ""
echo "Waiting for services to start..."
sleep 15

# Verify
echo ""
echo "============================================="
echo "✓ Setup complete!"
echo "============================================="
echo ""
echo "Service endpoints:"
echo "  API Gateway:        http://localhost:8080"
echo "  Auth Service:       http://localhost:8001"
echo "  Catalog Service:    http://localhost:8002"
echo "  Order Service:      http://localhost:8003"
echo "  Payment Service:    http://localhost:8004"
echo "  Notification Svc:   http://localhost:8005"
echo "  Audit Service:      http://localhost:8006"
echo ""
echo "Observability:"
echo "  Grafana:            http://localhost:3001 (admin / from .env)"
echo "  Prometheus:         http://localhost:9090"
echo "  Jaeger:             http://localhost:16686"
echo "  Loki:               http://localhost:3100"
echo "  Kafka UI:           http://localhost:8090"
echo ""
echo "Next steps:"
echo "  1. Run database migrations: ./scripts/migrate.sh"
echo "  2. Run tests: ./scripts/test.sh"
echo "  3. View logs: docker-compose logs -f"
echo ""
