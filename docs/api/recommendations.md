# Recommendations API (Recommendation Service)

> Service: `recommendation-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8021`

Product recommendations: collaborative filtering, frequently bought together, trending.

## Endpoints

### GET /recommendations/for-you
Personalized recommendations untuk user (collaborative filtering).

```json
{
  "user_id": "uuid",
  "source": "collaborative_filtering",
  "recommendations": [
    {
      "product_id": "uuid",
      "name": "Recommended Product",
      "score": 0.95,
      "reason": "similar_users_bought"
    }
  ]
}
```

Cached 1 jam per user.

### GET /recommendations/frequently-bought-together/{product_id}
Products frequently bought together (association rules).

```json
{
  "product_id": "uuid",
  "source": "association_rules",
  "recommendations": [
    {
      "product_id": "uuid",
      "confidence": 0.65,
      "support": 0.12
    }
  ]
}
```

### GET /recommendations/users-also-viewed/{product_id}
Users who viewed this also viewed (co-view).

### GET /recommendations/trending
Trending products (high sales velocity 24h).

```json
{
  "source": "trending_24h",
  "recommendations": [
    {"product_id": "uuid", "sales_24h": 145, "trend_score": 0.95}
  ]
}
```

Cached 30 menit (lebih dinamis dari for-you).

### GET /recommendations/recently-viewed
User's recently viewed products (from Redis list, max 50).

### POST /recommendations/track-view
Track product view (called from frontend).

```json
{ "product_id": "uuid" }
```

Update Redis:
- `recently_viewed:{user_id}` - List of recently viewed product_ids (max 50, 30 day TTL)
- `trending:{YYYYMMDDHH}` - Sorted set untuk trending calculation

## ML Models (Planned)

### Collaborative Filtering
- **Algorithm**: Matrix Factorization (SVD) atau Neural Collaborative Filtering
- **Training data**: user-product interactions (view, cart, purchase)
- **Retrain**: weekly
- **Features**: implicit feedback (clicks, time spent)

### Content-Based
- **Algorithm**: TF-IDF atau BERT embeddings dari product description
- **Use case**: cold start (user baru), serendipity

### Association Rules (Frequently Bought Together)
- **Algorithm**: Apriori atau FP-Growth
- **Training data**: order history (which products bought together)
- **Metrics**: support, confidence, lift
