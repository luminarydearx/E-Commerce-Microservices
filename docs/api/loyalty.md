# Loyalty API (Loyalty Service)

> Service: `loyalty-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8016`

Points, tiers, cashback, rewards redemption.

## Tiers

| Tier | Min Lifetime Points | Cashback Rate |
|------|---------------------|---------------|
| SILVER | 0 | 1% |
| GOLD | 1.000 | 2% |
| PLATINUM | 5.000 | 3% |
| DIAMOND | 20.000 | 5% |

## Points Earning

- 1 point per Rp 100 spent (0.01 = 1%)
- Cashback otomatis: percentage sesuai tier, ditambah ke cashback_balance
- Points expire setelah 1 tahun

## Endpoints

### GET /loyalty/me
Get membership detail user.

```json
{
  "user_id": "uuid",
  "tier": "GOLD",
  "points_balance": 1500,
  "lifetime_points": 2300,
  "cashback_balance": 45000,
  "tier_updated_at": "2026-06-01T00:00:00Z",
  "next_tier": "PLATINUM",
  "points_to_next_tier": 2700,
  "cashback_rate_percent": 2
}
```

### POST /loyalty/earn
Internal: Award points setelah order complete (dipanggil order-service).

```json
{
  "user_id": "uuid",
  "order_id": "uuid",
  "amount": 500000
}
```

Response: points_earned, cashback_earned, new_balance, tier (jika upgrade terdeteksi).

### POST /loyalty/redeem
Redeem points untuk reward.

```json
{ "reward_id": "uuid" }
```

Validasi:
- Points balance >= reward.points_cost
- User tier >= reward.min_tier
- Reward masih ada stock (jika ada stock limit)

Response: voucher_code yang bisa dipakai di checkout.

### GET /loyalty/rewards
List rewards yang available + flag `can_redeem` per user.

### GET /loyalty/transactions
History transaksi points (earn/redeem/expire).
