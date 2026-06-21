#!/usr/bin/env python3
"""
E-Commerce Microservices — End-to-End User Journey Demo
=========================================================

Simulates a complete buyer journey:
  1. Register new buyer (with idempotency key)
  2. Login (get access token)
  3. Get user profile
  4. Browse products (public)
  5. View product detail
  6. Add to cart
  7. View cart
  8. Checkout (create order)
  9. Create payment (idempotent)
  10. Check payment status
  11. List user orders
  12. Add product review
  13. List product reviews
  14. Add product to wishlist
  15. Get wishlist
  16. Validate coupon (expect: invalid)
  17. Check loyalty membership
  18. Logout

Also simulates a seller journey:
  S1. Register seller
  S2. Login seller
  S3. Create product
  S4. Update product
  S5. Adjust stock
  S6. Get seller dashboard
  S7. List own products

And admin journey:
  A1. Login as superadmin (pre-seeded)
  A2. List all users
  A3. View audit log
  A4. View error log
  A5. View fraud flags
  A6. Check system health

Usage:
  python3 scripts/demo/user_journey.py --gateway http://localhost:8080
  python3 scripts/demo/user_journey.py --skip-seller
  python3 scripts/demo/user_journey.py --only-buyer
"""
from __future__ import annotations

import argparse
import json
import random
import string
import sys
import time
import uuid
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)


# ANSI colors
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def log_step(num: int, msg: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}[{num:02d}] {msg}{C.RESET}")


def log_info(msg: str) -> None:
    print(f"{C.BLUE}    ℹ {msg}{C.RESET}")


def log_success(msg: str) -> None:
    print(f"{C.GREEN}    ✓ {msg}{C.RESET}")


def log_warning(msg: str) -> None:
    print(f"{C.YELLOW}    ⚠ {msg}{C.RESET}")


def log_error(msg: str) -> None:
    print(f"{C.RED}    ✗ {msg}{C.RESET}")


def log_data(label: str, data: Any, max_chars: int = 200) -> None:
    text = json.dumps(data, indent=2, default=str) if not isinstance(data, str) else data
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    print(f"{C.GRAY}    {label}: {text}{C.RESET}")


def random_email() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"demo_{suffix}@example.com"


def random_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class APIClient:
    """Simple HTTP client with auth."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)
        self.access_token: str | None = None
        self.user_id: str | None = None
        self.roles: list[str] = []

    def _headers(self, extra: dict | None = None, with_auth: bool = True,
                 with_idempotency: bool = False) -> dict:
        h = {"Content-Type": "application/json"}
        if with_auth and self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        if with_idempotency:
            h["Idempotency-Key"] = str(uuid.uuid4())
        if extra:
            h.update(extra)
        return h

    def get(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return self.client.get(url, headers=self._headers(**kwargs))

    def post(self, path: str, json_body: dict | None = None, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return self.client.post(url, json=json_body, headers=self._headers(**kwargs))

    def put(self, path: str, json_body: dict, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return self.client.put(url, json=json_body, headers=self._headers(**kwargs))

    def patch(self, path: str, json_body: dict, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return self.client.patch(url, json=json_body, headers=self._headers(**kwargs))

    def delete(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return self.client.delete(url, headers=self._headers(**kwargs))

    def check_health(self) -> bool:
        try:
            resp = self.client.get(f"{self.base_url}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


# ===== Buyer Journey =====

def buyer_journey(client: APIClient) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}═══════════════════════════════════════════════════")
    print(f"  BUYER JOURNEY")
    print(f"═══════════════════════════════════════════════════{C.RESET}")

    email = random_email()
    password = "DemoP@ss123!"
    log_data("email", email)

    # 1. Register
    log_step(1, "Register new buyer")
    resp = client.post(
        "/api/v1/auth/register",
        json_body={
            "email": email,
            "password": password,
            "full_name": "Demo Buyer",
            "phone": "+6281234567890",
            "role": "buyer",
        },
        with_auth=False,
        with_idempotency=True,
    )
    if resp.status_code == 201:
        data = resp.json()
        client.access_token = data["access_token"]
        client.user_id = data["user"]["id"]
        client.roles = [data["user"]["role"]]
        log_success(f"Registered. User ID: {client.user_id}")
        log_data("role", data["user"]["role"])
    else:
        log_error(f"Register failed: {resp.status_code} {resp.text}")
        return

    # 2. Login (verify password works)
    log_step(2, "Login with credentials")
    resp = client.post(
        "/api/v1/auth/login",
        json_body={"email": email, "password": password},
        with_auth=False,
    )
    if resp.status_code == 200:
        data = resp.json()
        client.access_token = data["access_token"]
        log_success("Login successful")
        log_data("expires_in", f"{data['expires_in']}s")
    else:
        log_error(f"Login failed: {resp.status_code}")
        return

    # 3. Get profile
    log_step(3, "Get user profile")
    resp = client.get("/api/v1/users/me")
    if resp.status_code == 200:
        log_success(f"Profile: {resp.json()['email']}")
    else:
        log_error(f"Get profile failed: {resp.status_code}")

    # 4. Browse products
    log_step(4, "Browse products (public)")
    resp = client.get("/api/v1/products?size=5", with_auth=False)
    if resp.status_code == 200:
        data = resp.json()
        products = data.get("content", []) if isinstance(data, dict) else data.get("data", [])
        log_success(f"Found {len(products)} products")
        for p in products[:3]:
            log_data("product", f"{p.get('name', '?')} - Rp {p.get('price', 0):,}")
        if not products:
            log_warning("No products yet (need seller to create)")
            return
        product_id = products[0]["id"]
        product_name = products[0].get("name", "Unknown")
        product_price = products[0].get("price", 0)
    else:
        log_error(f"Browse products failed: {resp.status_code}")
        return

    # 5. View product detail
    log_step(5, f"View product detail: {product_name}")
    resp = client.get(f"/api/v1/products/{product_id}", with_auth=False)
    if resp.status_code == 200:
        p = resp.json()
        log_success(f"Product: {p.get('name')}")
        log_data("available_stock", p.get("available_stock", 0))
    else:
        log_error(f"Get product failed: {resp.status_code}")

    # 6. Add to cart
    log_step(6, "Add product to cart")
    resp = client.post(
        "/api/v1/cart",
        json_body={"product_id": product_id, "quantity": 2},
    )
    if resp.status_code == 200:
        cart = resp.json()
        log_success(f"Cart has {len(cart.get('items', []))} items")
    else:
        log_error(f"Add to cart failed: {resp.status_code} {resp.text[:200]}")
        return

    # 7. View cart
    log_step(7, "View cart")
    resp = client.get("/api/v1/cart")
    if resp.status_code == 200:
        cart = resp.json()
        log_success(f"Cart total items: {len(cart.get('items', []))}")
        for item in cart.get("items", []):
            log_data("item", f"{item.get('product_name')} x{item.get('quantity')} = Rp {item.get('unit_price', 0) * item.get('quantity', 0):,}")

    # 8. Checkout
    log_step(8, "Checkout (create order)")
    resp = client.post(
        "/api/v1/checkout",
        json_body={
            "shipping_address": "Jl. Sudirman No. 1, Jakarta Pusat, DKI Jakarta 10220",
            "payment_method": "credit_card",
        },
        with_idempotency=True,
    )
    if resp.status_code == 201:
        order = resp.json()
        order_id = order["id"]
        log_success(f"Order created: {order_id}")
        log_data("status", order["status"])
        log_data("total", f"Rp {order['total_amount']:,.0f}")
        log_data("expires_at", order["expires_at"])
    else:
        log_error(f"Checkout failed: {resp.status_code} {resp.text[:300]}")
        return

    # 9. Create payment
    log_step(9, "Create payment (idempotent)")
    resp = client.post(
        "/api/v1/payments",
        json_body={
            "order_id": order_id,
            "method": "credit_card",
            "provider": "midtrans",
        },
        with_idempotency=True,
    )
    payment_id = None
    if resp.status_code == 201:
        payment = resp.json()
        payment_id = payment["id"]
        log_success(f"Payment created: {payment_id}")
        log_data("status", payment["status"])
        log_data("amount", f"Rp {payment['amount']:,.0f}")
    else:
        log_error(f"Payment failed: {resp.status_code} {resp.text[:300]}")

    # 10. Check payment status
    if payment_id:
        log_step(10, "Check payment status")
        resp = client.get(f"/api/v1/payments/{payment_id}")
        if resp.status_code == 200:
            payment = resp.json()
            log_success(f"Payment status: {payment['status']}")
        else:
            log_error(f"Get payment failed: {resp.status_code}")

    # 11. List orders
    log_step(11, "List user orders")
    resp = client.get("/api/v1/orders?size=10")
    if resp.status_code == 200:
        data = resp.json()
        orders = data.get("data", [])
        log_success(f"User has {data.get('total', 0)} orders")
        for o in orders[:3]:
            log_data("order", f"{o['id'][:8]}... status={o['status']} total=Rp {o['total_amount']:,.0f}")

    # 12. Add product review (will fail because order not delivered, but demonstrate API)
    log_step(12, "Attempt to review product (expected to fail until delivered)")
    resp = client.post(
        "/api/v1/reviews",
        json_body={
            "product_id": product_id,
            "order_item_id": str(uuid.uuid4()),
            "rating": 5,
            "title": "Excellent product!",
            "content": "Great quality, fast shipping. Highly recommend.",
            "images": [],
        },
        with_idempotency=True,
    )
    if resp.status_code == 201:
        log_success("Review created")
    else:
        log_warning(f"Review not created (expected): {resp.status_code} - {resp.text[:100]}")

    # 13. List product reviews
    log_step(13, f"List reviews for product: {product_name}")
    resp = client.get(f"/api/v1/products/{product_id}/reviews", with_auth=False)
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Product has {data.get('total', 0)} reviews")

    # 14. Add to wishlist
    log_step(14, "Add product to wishlist")
    resp = client.post(
        "/api/v1/wishlist/items",
        json_body={
            "product_id": product_id,
            "notify_price_drop": True,
            "target_price": int(product_price * 0.9),  # 10% below current
        },
    )
    if resp.status_code == 201:
        log_success("Added to wishlist")
    elif resp.status_code == 409:
        log_info("Already in wishlist")
    else:
        log_error(f"Wishlist failed: {resp.status_code}")

    # 15. Get wishlist
    log_step(15, "Get wishlist")
    resp = client.get("/api/v1/wishlist")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        log_success(f"Wishlist has {len(items)} items")

    # 16. Validate coupon (invalid code)
    log_step(16, "Validate coupon (expect invalid)")
    resp = client.post(
        "/api/v1/coupons/validate",
        json_body={
            "code": "INVALID_CODE",
            "user_id": client.user_id,
            "cart_total": product_price * 2,
            "cart_items": [{"product_id": product_id, "price": product_price, "quantity": 2}],
        },
    )
    if resp.status_code == 404:
        log_success("Correctly rejected invalid coupon")
    else:
        log_data("response", resp.text[:200])

    # 17. Check loyalty membership
    log_step(17, "Check loyalty membership")
    resp = client.get("/api/v1/loyalty/me")
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Tier: {data.get('tier')}, Points: {data.get('points_balance')}")
    else:
        log_warning(f"Loyalty service not available: {resp.status_code}")

    # 18. Get recommendations
    log_step(18, "Get personalized recommendations")
    resp = client.get("/api/v1/recommendations/for-you?limit=5")
    if resp.status_code == 200:
        data = resp.json()
        recs = data.get("recommendations", [])
        log_success(f"Got {len(recs)} recommendations")
    else:
        log_warning(f"Recommendation service not available: {resp.status_code}")

    # 19. Logout
    log_step(19, "Logout")
    resp = client.post("/api/v1/auth/logout")
    if resp.status_code == 204:
        log_success("Logged out successfully")
    else:
        log_warning(f"Logout returned {resp.status_code}")


# ===== Seller Journey =====

def seller_journey(client: APIClient) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}═══════════════════════════════════════════════════")
    print(f"  SELLER JOURNEY")
    print(f"═══════════════════════════════════════════════════{C.RESET}")

    email = random_email()
    password = "DemoP@ss123!"

    log_step(1, "Register new seller")
    resp = client.post(
        "/api/v1/auth/register",
        json_body={"email": email, "password": password, "full_name": "Demo Seller", "role": "seller"},
        with_auth=False,
        with_idempotency=True,
    )
    if resp.status_code == 201:
        data = resp.json()
        client.access_token = data["access_token"]
        client.user_id = data["user"]["id"]
        log_success(f"Seller registered: {client.user_id}")
    else:
        log_error(f"Register failed: {resp.status_code} {resp.text[:200]}")
        return

    log_step(2, "Setup seller profile")
    resp = client.post(
        "/api/v1/seller/profile",
        json_body={
            "store_name": f"Demo Store {random_str(4)}",
            "description": "We sell quality products at fair prices",
        },
    )
    if resp.status_code == 200:
        log_success("Seller profile created")
    else:
        log_warning(f"Profile setup: {resp.status_code}")

    log_step(3, "Create product")
    product_sku = f"DEMO-{random_str(6).upper()}"
    resp = client.post(
        "/api/v1/products",
        json_body={
            "sku": product_sku,
            "name": f"Demo Product {random_str(4)}",
            "description": "High-quality demo product for testing",
            "price": 150000,
            "stock": 100,
            "weight_grams": 500,
            "status": "ACTIVE",
        },
    )
    product_id = None
    if resp.status_code == 201:
        product = resp.json()
        product_id = product["id"]
        log_success(f"Product created: {product_id}")
        log_data("sku", product["sku"])
    else:
        log_error(f"Create product failed: {resp.status_code} {resp.text[:200]}")
        return

    log_step(4, "Update product")
    resp = client.put(
        f"/api/v1/products/{product_id}",
        json_body={"price": 145000, "description": "Updated description"},
    )
    if resp.status_code == 200:
        log_success("Product updated (price reduced to Rp 145,000)")
    else:
        log_error(f"Update failed: {resp.status_code}")

    log_step(5, "Adjust stock")
    resp = client.patch(
        f"/api/v1/products/{product_id}/stock",
        json_body={"new_stock": 150, "reason": "Restocked from supplier"},
    )
    if resp.status_code == 204:
        log_success("Stock adjusted to 150")
    else:
        log_error(f"Stock adjust failed: {resp.status_code}")

    log_step(6, "Get seller dashboard")
    resp = client.get("/api/v1/seller/dashboard?period=30d")
    if resp.status_code == 200:
        data = resp.json()
        log_success("Dashboard retrieved")
        log_data("summary", data.get("summary", {}))
    else:
        log_warning(f"Dashboard: {resp.status_code}")


# ===== Admin Journey =====

def admin_journey(client: APIClient, admin_email: str, admin_password: str) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}═══════════════════════════════════════════════════")
    print(f"  ADMIN JOURNEY")
    print(f"═══════════════════════════════════════════════════{C.RESET}")

    log_step(1, f"Login as admin: {admin_email}")
    resp = client.post(
        "/api/v1/auth/login",
        json_body={"email": admin_email, "password": admin_password},
        with_auth=False,
    )
    if resp.status_code == 200:
        data = resp.json()
        client.access_token = data["access_token"]
        client.user_id = data["user"]["id"]
        client.roles = [data["user"]["role"]]
        log_success(f"Logged in as {data['user']['role']}")
    else:
        log_error(f"Admin login failed: {resp.status_code} {resp.text[:200]}")
        log_info("Make sure admin is pre-seeded via migration script")
        return

    log_step(2, "List all users")
    resp = client.get("/api/v1/admin/users?size=5")
    if resp.status_code == 200:
        users = resp.json()
        if isinstance(users, list):
            log_success(f"Found {len(users)} users")
        else:
            log_data("response", users)
    else:
        log_warning(f"List users: {resp.status_code}")

    log_step(3, "View audit log (last 5)")
    resp = client.get("/api/v1/admin/audit?size=5")
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Total audit entries: {data.get('total', 0)}")
        for entry in (data.get("data") or [])[:3]:
            log_data("audit", f"{entry.get('action', '?')} by {entry.get('actor_user_id', '?')[:8] if entry.get('actor_user_id') else 'system'}")
    else:
        log_warning(f"Audit log: {resp.status_code}")

    log_step(4, "View error log")
    resp = client.get("/api/v1/admin/errors?size=5")
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Total errors: {data.get('total', 0)}")
    else:
        log_warning(f"Errors: {resp.status_code}")

    log_step(5, "View fraud flags")
    resp = client.get("/api/v1/admin/fraud/flags?status_filter=OPEN&size=5")
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Open fraud flags: {data.get('total', 0)}")
    else:
        log_warning(f"Fraud flags: {resp.status_code}")

    log_step(6, "Check system health")
    resp = client.get("/api/v1/admin/system/health")
    if resp.status_code == 200:
        data = resp.json()
        log_success(f"Overall: {data.get('overall_status', 'unknown')}")
        services = data.get("services", {})
        for svc, info in list(services.items())[:5]:
            status = info.get("status", "?")
            emoji = "✓" if status == "up" else "✗"
            print(f"        {emoji} {svc}: {status}")
    else:
        log_warning(f"System health: {resp.status_code}")

    log_step(7, "Get analytics overview")
    resp = client.get("/api/v1/analytics/overview?period=7d")
    if resp.status_code == 200:
        data = resp.json()
        kpis = data.get("kpis", {})
        log_success("Analytics retrieved")
        for k, v in list(kpis.items())[:5]:
            log_data(k, v)
    else:
        log_warning(f"Analytics: {resp.status_code}")


# ===== Main =====

def main() -> int:
    parser = argparse.ArgumentParser(description="E-Commerce Microservices Demo")
    parser.add_argument("--gateway", default="http://localhost:8080",
                        help="API Gateway URL (default: http://localhost:8080)")
    parser.add_argument("--admin-email", default="admin@ecommerce.local",
                        help="Admin email for admin journey")
    parser.add_argument("--admin-password", default="AdminP@ss123!",
                        help="Admin password")
    parser.add_argument("--only-buyer", action="store_true",
                        help="Run only buyer journey")
    parser.add_argument("--only-seller", action="store_true",
                        help="Run only seller journey")
    parser.add_argument("--only-admin", action="store_true",
                        help="Run only admin journey")
    parser.add_argument("--skip-buyer", action="store_true")
    parser.add_argument("--skip-seller", action="store_true")
    parser.add_argument("--skip-admin", action="store_true")
    parser.add_argument("--pause", type=float, default=0.5,
                        help="Pause between steps (seconds)")

    args = parser.parse_args()

    print(f"{C.BOLD}{C.CYAN}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   E-Commerce Microservices — End-to-End Demo              ║")
    print("║   Simulating user journeys through all 20+ services       ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"{C.RESET}")

    print(f"Gateway: {args.gateway}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Check gateway
    client = APIClient(args.gateway)
    if not client.check_health():
        log_error(f"Cannot reach API Gateway at {args.gateway}")
        log_info("Make sure services are running: docker-compose up -d")
        return 1
    log_success("API Gateway is healthy")

    run_buyer = not (args.only_seller or args.only_admin) and not args.skip_buyer
    run_seller = not (args.only_buyer or args.only_admin) and not args.skip_seller
    run_admin = not (args.only_buyer or args.only_seller) and not args.skip_admin

    try:
        if run_buyer:
            buyer_journey(client)
            time.sleep(args.pause)

        if run_seller:
            seller_journey(client)
            time.sleep(args.pause)

        if run_admin:
            admin_journey(client, args.admin_email, args.admin_password)

    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Demo interrupted by user{C.RESET}")
        return 130
    except httpx.ConnectError as e:
        log_error(f"Connection error: {e}")
        return 1
    except Exception as e:
        log_error(f"Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print(f"\n{C.BOLD}{C.GREEN}═══════════════════════════════════════════════════")
    print(f"  Demo Complete!")
    print(f"═══════════════════════════════════════════════════{C.RESET}")
    print(f"\n{C.GRAY}Tip: Run 'docker-compose logs -f' to see service logs in real-time")
    print(f"Tip: Open Grafana at http://localhost:3001 to see metrics")
    print(f"Tip: Open Jaeger at http://localhost:16686 to see distributed traces{C.RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
