# Search API (Search Service)

> Service: `search-service` (Python/FastAPI + Elasticsearch)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8012`

Full-text search dengan autocomplete, faceted search, typo tolerance.

## Endpoints

### POST /search
Search products dengan filter & facets.

```json
{
  "query": "iphone 15",
  "category_id": "uuid-optional",
  "seller_id": "uuid-optional",
  "min_price": 5000000,
  "max_price": 25000000,
  "min_rating": 4,
  "in_stock": true,
  "sort_by": "relevance",
  "page": 0,
  "size": 20
}
```

**Sort options:** `relevance`, `price_asc`, `price_desc`, `newest`, `rating`, `popular`

**Response 200 OK:**
```json
{
  "data": [ProductDoc],
  "total": 145,
  "page": 0,
  "size": 20,
  "facets": {
    "categories": [
      {"id": "uuid", "count": 89},
      {"id": "uuid", "count": 56}
    ],
    "price_ranges": [
      {"key": "*-50000.0", "from": null, "to": 50000, "count": 12},
      {"key": "50000.0-100000.0", "from": 50000, "to": 100000, "count": 34}
    ]
  },
  "took_ms": 23,
  "cached": false
}
```

### GET /search/autocomplete
Typeahead autocomplete untuk search box.

```
GET /search/autocomplete?q=iph
```

**Response 200 OK:**
```json
{
  "suggestions": [
    {"text": "iPhone 15 Pro", "product_id": "uuid", "score": 0.95},
    {"text": "iPhone 14", "product_id": "uuid", "score": 0.85}
  ]
}
```

Cached 5 menit di Redis.

### GET /search/popular
Trending searches.

### POST /search/index
Index/update product (dipanggil oleh catalog-service via Kafka event).

### DELETE /search/index/{product_id}
Hapus product dari index.

## Elasticsearch Configuration

- **Analyzer**: Indonesian (stopwords + stemming)
- **Fuzziness**: AUTO (typo tolerance)
- **Completion suggester**: untuk autocomplete
- **Aggregations**: categories (terms), price_ranges (range), avg_rating (avg)

## Fallback

Jika ES unavailable: return empty result dengan `"fallback": true` (service tidak down, hanya degraded).

## Caching

- Search results: 5 menit di Redis
- Autocomplete: 5 menit
- Popular searches: 1 jam
