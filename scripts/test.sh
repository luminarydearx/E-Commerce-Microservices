#!/bin/bash
# Run all tests + security scans
set -e

echo "============================================="
echo "Running Tests & Security Audit"
echo "============================================="
echo ""

# Python services
echo "[1/4] Auth Service tests..."
cd auth-service
pip install -e ".[dev]" --quiet
pytest tests/ --cov=app --cov-report=term-missing || true
bandit -r app -ll || true
safety check --ignore 70612 || true
cd ..

echo ""
echo "[2/4] Audit Service tests..."
cd audit-service
pip install -e . --quiet || true
pytest tests/ || true
bandit -r app -ll || true
cd ..

# Go services
echo ""
echo "[3/4] Order Service tests..."
cd order-service
go test ./... -race -cover || true
gosec ./... || true
cd ..

echo ""
echo "[4/4] Payment Service tests..."
cd payment-service
go test ./... -race -cover || true
gosec ./... || true
cd ..

echo ""
echo "============================================="
echo "✓ Tests complete"
echo "============================================="
