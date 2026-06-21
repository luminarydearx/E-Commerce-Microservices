# Quick Helm install guide

## Prerequisites

- Kubernetes 1.27+
- Helm 3.13+
- cert-manager (for TLS)
- nginx-ingress-controller
- kube-prometheus-stack (for ServiceMonitors)
- Bitnami Helm repo added:
  ```bash
  helm repo add bitnami https://charts.bitnami.com/bitnami
  helm repo update
  ```

## Install

### 1. Create namespace
```bash
kubectl create namespace ecommerce
```

### 2. Create secrets (DO NOT commit values.yaml with real secrets)
```bash
# JWT keys
kubectl create secret generic jwt-keys -n ecommerce \
  --from-file=private.pem=./keys/private.pem \
  --from-file=public.pem=./keys/public.pem

# Database password
kubectl create secret generic db-credentials -n ecommerce \
  --from-literal=password=$(openssl rand -base64 32)

# Provider keys
kubectl create secret generic payment-providers -n ecommerce \
  --from-literal=midtrans-server-key=$MIDTRANS_SERVER_KEY \
  --from-literal=xendit-secret-key=$XENDIT_SECRET_KEY \
  --from-literal=webhook-secret=$(openssl rand -hex 32)
```

### 3. Copy values.yaml and edit
```bash
cp deploy/helm/values.yaml my-values.yaml
# Edit my-values.yaml with your real values
```

### 4. Install
```bash
helm install ecommerce deploy/helm \
  -f my-values.yaml \
  -n ecommerce \
  --create-namespace \
  --dependency-update \
  --timeout 10m
```

### 5. Verify
```bash
kubectl get pods -n ecommerce
kubectl get svc -n ecommerce
kubectl get ingress -n ecommerce

# Wait for all pods to be ready
kubectl wait --for=condition=ready pod --all -n ecommerce --timeout=300s

# Test API
kubectl port-forward svc/api-gateway 8080:8080 -n ecommerce
curl http://localhost:8080/health
```

## Upgrade
```bash
# Update values or chart, then:
helm upgrade ecommerce deploy/helm -f my-values.yaml -n ecommerce

# Rollback if needed
helm rollback ecommerce 0 -n ecommerce
```

## Uninstall
```bash
helm uninstall ecommerce -n ecommerce
# PVCs are retained by default. To delete:
kubectl delete pvc --all -n ecommerce
```

## Multi-environment

```bash
# Dev (cheap, 1 replica each)
helm install ecommerce-dev deploy/helm \
  -f deploy/helm/values.yaml \
  -f deploy/helm/values-dev.yaml \
  -n ecommerce-dev --create-namespace

# Staging
helm install ecommerce-staging deploy/helm \
  -f deploy/helm/values.yaml \
  -f deploy/helm/values-staging.yaml \
  -n ecommerce-staging --create-namespace

# Production
helm install ecommerce deploy/helm \
  -f deploy/helm/values.yaml \
  -f deploy/helm/values-prod.yaml \
  -n ecommerce --create-namespace
```

## CI/CD with Helm

```yaml
# .github/workflows/deploy.yml
- name: Deploy
  run: |
    helm upgrade --install ecommerce deploy/helm \
      -f deploy/helm/values-prod.yaml \
      --set global.imageTag=${{ github.sha }} \
      -n ecommerce \
      --wait --timeout 10m
```

## Troubleshooting

### Pods in CrashLoopBackOff
```bash
kubectl describe pod <pod-name> -n ecommerce
kubectl logs <pod-name> -n ecommerce --previous
```

### Service not reachable
```bash
kubectl get endpoints -n ecommerce
kubectl exec -it pod/api-gateway-xxx -n ecommerce -- curl http://auth-service:8001/health
```

### Database connection issues
```bash
kubectl exec -it pod/postgresql-0 -n ecommerce -- psql -U ecommerce -d auth_db -c "SELECT 1"
```
