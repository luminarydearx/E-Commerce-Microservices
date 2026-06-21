# Reviews API (Review Service)

> Service: `review-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8007`

Product reviews, ratings, helpful votes, seller responses, moderation.

## Anti-Fraud Features

- **Verified purchase required**: User hanya bisa review product yang pernah dibeli (cek via order-service)
- **One review per product per user**: Unique constraint `(user_id, product_id)`
- **Edit window**: Review bisa diedit dalam 24 jam setelah dibuat
- **Profanity filter**: Kata kasar di-replace `[REDACTED]` otomatis
- **Moderation queue**: Review dengan profanity masuk antrian moderasi manual

---

## Endpoints

### POST /reviews
Buat review baru.

**Request Body:**
```json
{
  "product_id": "uuid",
  "order_item_id": "uuid",
  "rating": 5,
  "title": "Excellent product!",
  "content": "Fast shipping, great quality. Highly recommend.",
  "images": ["https://..."],
  "is_anonymous": false
}
```

**Validasi:**
- `rating`: 1-5
- `title`: max 200 char
- `content`: max 5000 char
- `images`: max 5 images
- `order_item_id` wajib (anti-fraud: verify purchase)
- User belum pernah review product ini sebelumnya

**Behavior:**
1. Verify user purchased this product (via order-service gRPC call)
2. Check existing review (unique constraint)
3. Sanitize content (profanity filter)
4. If profanity detected → moderation_status = PENDING (butuh review admin)
5. Create review
6. Update product rating summary (materialized view)

**Response 201 Created:**
```json
{
  "id": "uuid",
  "product_id": "uuid",
  "rating": 5,
  "title": "Excellent product!",
  "content": "Fast shipping, great quality.",
  "images": ["https://..."],
  "is_anonymous": false,
  "is_edited": false,
  "helpful_count": 0,
  "not_helpful_count": 0,
  "seller_response": null,
  "moderation_status": "APPROVED",
  "created_at": "...",
  "updated_at": "..."
}
```

**Errors:**
- `409 Conflict` - sudah review product ini
- `422 Validation Error` - rating invalid / content too long

---

### GET /products/{product_id}/reviews
List review untuk product.

**Query Params:**
| Param | Default | Description |
|-------|---------|-------------|
| `page` | 0 | 0-indexed |
| `size` | 20 | max 100 |
| `sort` | `recent` | `recent`/`helpful`/`highest`/`lowest` |
| `rating_filter` | - | Filter by rating (1-5) |
| `with_images` | false | Hanya review dengan foto |

**Response 200 OK:**
```json
{
  "data": [ReviewResponse],
  "total": 234,
  "page": 0,
  "size": 20
}
```

---

### GET /products/{product_id}/rating-summary
Get rating summary product.

**Response 200 OK:**
```json
{
  "product_id": "uuid",
  "average_rating": 4.5,
  "total_reviews": 234,
  "distribution": {
    "5": 180,
    "4": 30,
    "3": 15,
    "2": 5,
    "1": 4
  }
}
```

Data dari materialized view `review.product_rating_summary` yang di-refresh secara periodik.

---

### GET /reviews/{review_id}
Get detail review.

---

### PUT /reviews/{review_id}
Edit review (hanya owner, dalam 24 jam).

**Request Body:**
```json
{
  "rating": 4,
  "title": "Updated title",
  "content": "Updated content",
  "images": []
}
```

**Behavior:**
- Set `is_edited = true`
- Reset moderation_status ke APPROVED (atau PENDING jika profanity)

---

### DELETE /reviews/{review_id}
Soft delete review (hanya owner).

---

### POST /reviews/{review_id}/helpful
Vote helpful/not helpful.

**Request Body:**
```json
{ "helpful": true }
```

**Behavior:**
- 1 user 1 vote per review (unique constraint)
- Jika vote lagi dengan nilai sama → idempotent
- Jika vote lagi dengan nilai beda → update vote, recalculate counts
- Counts di-update via DB trigger

**Response 200 OK:**
```json
{
  "helpful_count": 45,
  "not_helpful_count": 3
}
```

---

### POST /reviews/{review_id}/seller-response
Seller respond ke review (hanya seller yang punya product).

**Request Body:**
```json
{ "content": "Thank you for your feedback!" }
```

---

### GET /users/{user_id}/reviews
List semua review dari user (owner atau admin only).

---

### POST /admin/reviews/{review_id}/moderate
Admin moderate review.

**Query Params:**
- `action`: `hide` / `approve` / `reject`
- `reason`: alasan moderasi

---

## Data Model

```sql
CREATE TABLE review.reviews (
    id UUID PRIMARY KEY,
    product_id UUID NOT NULL,
    order_item_id UUID NOT NULL,
    user_id UUID NOT NULL,
    seller_id UUID NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 5000),
    images JSONB,
    is_anonymous BOOLEAN DEFAULT FALSE,
    is_edited BOOLEAN DEFAULT FALSE,
    is_hidden BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    helpful_count INTEGER DEFAULT 0,
    not_helpful_count INTEGER DEFAULT 0,
    seller_response TEXT,
    seller_response_at TIMESTAMPTZ,
    moderation_status VARCHAR(20) DEFAULT 'APPROVED',
    moderation_reason VARCHAR(500),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    version INTEGER DEFAULT 1,
    CONSTRAINT uq_user_product_review UNIQUE (user_id, product_id)
);

CREATE TABLE review.helpful_votes (
    id UUID PRIMARY KEY,
    review_id UUID REFERENCES review.reviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    helpful BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ,
    CONSTRAINT uq_helpful_review_user UNIQUE (review_id, user_id)
);

-- Materialized view for fast rating summary
CREATE MATERIALIZED VIEW review.product_rating_summary AS
SELECT product_id, AVG(rating), COUNT(*), ...
FROM review.reviews WHERE is_deleted=FALSE AND is_hidden=FALSE AND moderation_status='APPROVED'
GROUP BY product_id;
```

## Audit Events

- `review.create`
- `review.update`
- `review.delete`
- `review.helpful_vote`
- `review.seller_response`
- `admin.review_moderate`
