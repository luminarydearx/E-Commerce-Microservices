#!/bin/bash
# Bash version of user journey demo (lightweight, no Python needed)
# Simpler than Python version — just curls through the flow
set -e

GATEWAY="${GATEWAY:-http://localhost:8080}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@ecommerce.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-AdminP@ss123!}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step() {
    echo -e "\n${CYAN}[$1] $2${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓ $1${NC}"
}

print_warn() {
    echo -e "  ${YELLOW}⚠ $1${NC}"
}

print_fail() {
    echo -e "  ${RED}✗ $1${NC}"
}

print_data() {
    echo -e "  ${BLUE}ℹ $1: $2${NC}"
}

echo "================================================"
echo "  E-Commerce Microservices Demo (Bash)"
echo "  Gateway: $GATEWAY"
echo "================================================"

# Check gateway
if ! curl -s -f "$GATEWAY/health" > /dev/null; then
    print_fail "Cannot reach gateway. Start services with: docker-compose up -d"
    exit 1
fi
print_ok "Gateway is healthy"

# === Buyer Journey ===
echo -e "\n${CYAN}=== BUYER JOURNEY ===${NC}"

EMAIL="demo_$(date +%s)@example.com"
PASSWORD="DemoP@ss123!"
IDEM_KEY=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)

print_step 1 "Register new buyer: $EMAIL"
RESP=$(curl -s -X POST "$GATEWAY/api/v1/auth/register" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $IDEM_KEY" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"full_name\":\"Demo Buyer\",\"role\":\"buyer\"}")

TOKEN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
    print_fail "Register failed: $RESP"
    exit 1
fi
print_ok "Registered. Token obtained."
USER_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['user']['id'])" 2>/dev/null)
print_data "user_id" "$USER_ID"

print_step 2 "Login"
RESP=$(curl -s -X POST "$GATEWAY/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)
print_ok "Login successful"

print_step 3 "Get profile"
RESP=$(curl -s "$GATEWAY/api/v1/users/me" -H "Authorization: Bearer $TOKEN")
print_ok "Profile retrieved"

print_step 4 "Browse products"
RESP=$(curl -s "$GATEWAY/api/v1/products?size=3")
PRODUCT_COUNT=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('content',[])))" 2>/dev/null || echo "0")
print_ok "Found $PRODUCT_COUNT products"

if [ "$PRODUCT_COUNT" = "0" ]; then
    print_warn "No products yet. Run seller journey first: ./scripts/demo/user_journey.sh --seller"
    exit 0
fi

PRODUCT_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['content'][0]['id'])" 2>/dev/null)
PRODUCT_NAME=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['content'][0]['name'])" 2>/dev/null)
print_data "product" "$PRODUCT_NAME"

print_step 5 "View product detail"
RESP=$(curl -s "$GATEWAY/api/v1/products/$PRODUCT_ID")
print_ok "Detail retrieved"

print_step 6 "Add to cart"
RESP=$(curl -s -X POST "$GATEWAY/api/v1/cart" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"product_id\":\"$PRODUCT_ID\",\"quantity\":2}")
print_ok "Added to cart"

print_step 7 "View cart"
RESP=$(curl -s "$GATEWAY/api/v1/cart" -H "Authorization: Bearer $TOKEN")
ITEMS=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('items',[])))" 2>/dev/null || echo "0")
print_ok "Cart has $ITEMS items"

print_step 8 "Checkout"
IDEM_KEY2=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)
RESP=$(curl -s -X POST "$GATEWAY/api/v1/checkout" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Idempotency-Key: $IDEM_KEY2" \
    -d '{"shipping_address":"Jl. Sudirman No. 1, Jakarta","payment_method":"credit_card"}')
ORDER_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
if [ -z "$ORDER_ID" ]; then
    print_fail "Checkout failed: $RESP"
    exit 1
fi
print_ok "Order created: $ORDER_ID"
ORDER_STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
ORDER_TOTAL=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_amount',0))" 2>/dev/null)
print_data "status" "$ORDER_STATUS"
print_data "total" "Rp $ORDER_TOTAL"

print_step 9 "Create payment"
IDEM_KEY3=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)
RESP=$(curl -s -X POST "$GATEWAY/api/v1/payments" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Idempotency-Key: $IDEM_KEY3" \
    -d "{\"order_id\":\"$ORDER_ID\",\"method\":\"credit_card\",\"provider\":\"midtrans\"}")
PAYMENT_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
if [ -n "$PAYMENT_ID" ]; then
    print_ok "Payment created: $PAYMENT_ID"
    PAYMENT_STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    print_data "status" "$PAYMENT_STATUS"
else
    print_warn "Payment creation response: $RESP"
fi

print_step 10 "List user orders"
RESP=$(curl -s "$GATEWAY/api/v1/orders?size=5" -H "Authorization: Bearer $TOKEN")
TOTAL_ORDERS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo "0")
print_ok "User has $TOTAL_ORDERS orders"

print_step 11 "Add to wishlist"
RESP=$(curl -s -X POST "$GATEWAY/api/v1/wishlist/items" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"product_id\":\"$PRODUCT_ID\",\"notify_price_drop\":true}")
print_ok "Added to wishlist"

print_step 12 "Check loyalty"
RESP=$(curl -s "$GATEWAY/api/v1/loyalty/me" -H "Authorization: Bearer $TOKEN")
TIER=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tier',''))" 2>/dev/null || echo "N/A")
print_ok "Loyalty tier: $TIER"

print_step 13 "Logout"
curl -s -X POST "$GATEWAY/api/v1/auth/logout" -H "Authorization: Bearer $TOKEN" > /dev/null
print_ok "Logged out"

echo -e "\n${GREEN}=== Demo Complete ===${NC}"
echo "Next steps:"
echo "  - View Grafana: http://localhost:3001"
echo "  - View Jaeger: http://localhost:16686"
echo "  - View Kafka UI: http://localhost:8090"
echo "  - View audit log: docker-compose exec audit-service curl -s localhost:8006/api/v1/admin/audit"
