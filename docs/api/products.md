# Products API (Catalog Service)

> Service: `catalog-service` (Java/Spring Boot)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8002`

Product catalog, inventory, category, stock reservation dengan atomic locking.

## Endpoints

### Public Endpoints

#### GET /products
List produk aktif dengan filter & pagination.

**Query Params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `search` | string | - | Search by name (ILIKE) |
| `category_id` | UUID | - | Filter by category |
| `min_price` | number | - | Min price |
| `max_price` | number | - | Max price |
| `sort_by` | string | `created` | `created`/`price`/`name`/`updated` |
| `sort_dir` | string | `desc` | `asc`/`desc` |
| `page` | int | 0 | 0-indexed |
| `size` | int | 20 | max 100 |

**Response 200 OK:**
```json
{
  "content": [
    {
      "id": "uuid",
      "seller_id": "uuid",
      "category_id": "uuid",
      "sku": "IPHONE-15-PRO-256",
      "name": "iPhone 15 Pro 256GB",
      "slug": "iphone-15-pro-256gb",
      "description": "Latest iPhone with A17 Pro chip",
      "price": 18999000.00,
      "currency": "IDR",
      "stock": 50,
      "reserved_stock": 5,
      "available_stock": 45,
      "weight_grams": 187,
      "image_urls": ["https://..."],
      "status": "ACTIVE",
      "is_active": true,
      "created_at": "2026-06-21T10:00:00Z",
      "updated_at": "2026-06-21T10:00:00Z"
    }
  ],
  "pageable": { "pageNumber": 0, "pageSize": 20 },
  "totalElements": 100,
  "totalPages": 5
}
```

---

#### GET /products/{id}
Get detail produk.

**Response 200 OK:** ProductResponse (sama seperti list item)

**Response 404:** Product tidak ditemukan

---

#### GET /categories
List semua kategori aktif.

---

### Seller Endpoints (role: seller/admin/superadmin)

#### POST /products
Buat produk baru.

**Request Body:**
```json
{
  "sku": "IPHONE-15-PRO-256",
  "name": "iPhone 15 Pro 256GB",
  "description": "Latest iPhone with A17 Pro chip",
  "price": 18999000.00,
  "stock": 50,
  "weight_grams": 187,
  "image_urls": ["https://..."],
  "category_id": "uuid-of-category",
  "status": "ACTIVE"
}
```

**Behavior:**
- SKU harus unik
- Slug auto-generated dari name (jika sudah ada, ditambah random suffix)
- Status default `DRAFT` (tidak visible di public list)
- Audit event `product.create` dipublish

**Response 201 Created:** ProductResponse

**Errors:**
- `409 Conflict` - SKU sudah ada
- `422 Validation Error` - price < 0, stock < 0, dll

---

#### PUT /products/{id}
Update produk. Seller hanya bisa update produk miliknya sendiri. Admin bisa update semua.

**Authorization:**
- Seller: hanya produk dengan `seller_id == user_id`
- Admin/Superadmin: semua produk

**Request Body (partial update):**
```json
{
  "name": "Updated Name",
  "price": 17999000.00,
  "stock": 100
}
```

**Response 200 OK:** Updated ProductResponse

**Concurrency:** Optimistic locking via `version` column. Jika konflik → 409.

---

#### DELETE /products/{id}
Soft delete produk (set `is_active=false`, `status=ARCHIVED`).

**Response 204 No Content**

---

#### PATCH /products/{id}/stock
Adjust stock dengan reason.

**Request Body:**
```json
{
  "new_stock": 80,
  "reason": "Restock from supplier"
}
```

**Response 204 No Content**

**Audit:** `product.stock_adjust` dengan before/after stock + reason

---

### Internal Endpoints (untuk service lain, mTLS protected)

#### POST /internal/products/{id}/reserve
Reserve stock atomically untuk checkout flow.

**Request Body:**
```json
{
  "product_id": "uuid",
  "quantity": 2,
  "user_id": "uuid",
  "cart_id": "uuid"
}
```

**Response 200 OK:**
```json
{
  "reservation_id": "uuid",
  "product_id": "uuid",
  "quantity": 2,
  "expires_at": "2026-06-21T10:15:00Z"
}
```

**Implementation:**
- Atomic SQL: `UPDATE products SET reserved_stock = reserved_stock + qty WHERE id = $1 AND stock - reserved_stock >= $qty`
- Isolation: SERIALIZABLE
- Reservation berlaku 15 menit, auto-expire via cron

**Errors:**
- `409 Conflict` - insufficient stock
- `422 Validation Error` - quantity invalid

---

#### POST /internal/reservations/{reservation_id}/release
Release reservation (batalkan, kembalikan stock).

**Response 204 No Content**

---

#### POST /internal/reservations/{reservation_id}/confirm
Confirm reservation (kurangi stock permanently setelah payment berhasil).

**Atomic SQL:**
```sql
UPDATE products 
SET stock = stock - qty, reserved_stock = reserved_stock - qty
WHERE id = $1 AND stock >= qty AND reserved_stock >= qty
```

**Response 204 No Content**

**Errors:**
- `409 Conflict` - stock atau reservation mismatch

---

## Data Model

```sql
CREATE TABLE catalog.products (
    id UUID PRIMARY KEY,
    seller_id UUID NOT NULL,
    category_id UUID REFERENCES catalog.categories(id),
    sku VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    price DECIMAL(19,2) NOT NULL CHECK (price > 0),
    currency VARCHAR(3) DEFAULT 'IDR',
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    reserved_stock INTEGER NOT NULL DEFAULT 0 CHECK (reserved_stock >= 0),
    weight_grams INTEGER,
    image_urls TEXT,  -- JSON array
    status VARCHAR(20) DEFAULT 'DRAFT',
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    version INTEGER DEFAULT 0,  -- optimistic lock
    CONSTRAINT chk_stock_reserved CHECK (reserved_stock <= stock),
    CONSTRAINT chk_product_status CHECK (status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'ARCHIVED'))
);

CREATE TABLE catalog.categories (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description VARCHAR(500),
    parent_id UUID REFERENCES catalog.categories(id),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE catalog.stock_reservations (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES catalog.products(id) ON DELETE CASCADE,
    cart_id UUID NOT NULL,
    user_id UUID NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'ACTIVE',
    UNIQUE(product_id, cart_id),
    CONSTRAINT chk_reservation_status CHECK (status IN ('ACTIVE', 'CONFIRMED', 'RELEASED', 'EXPIRED'))
);
```

## Search Performance

- Index pada `(is_active, status)` untuk filter produk aktif
- Index pada `price` untuk sort by price
- Trigram index (`gin_trgm_ops`) pada `name` untuk fuzzy search
- JSONB GIN index pada `metadata` untuk filter fleksibel
- Cache (Redis, TTL 5 menit) untuk product detail

## Cache Strategy

- **L1**: In-memory cache per instance (60s TTL)
- **L2**: Redis (5 min TTL)
- **L3**: PostgreSQL (source of truth)
- Invalidation: event-driven via Kafka `product.update` event

## Audit Events

- `product.create`
- `product.update`
- `product.delete`
- `product.stock_adjust`
- `product.reserve` (internal)
- `product.release_reservation` (internal)
- `product.confirm_reservation` (internal)
