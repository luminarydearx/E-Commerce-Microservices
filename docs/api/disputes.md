# Disputes API (Dispute Service)

> Service: `dispute-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8013`

Buyer-seller dispute resolution dengan admin mediation.

## Dispute Flow

```
OPEN ──seller_respond──▶ SELLER_RESPONDED ──buyer_escalate──▶ ESCALATED ──admin_resolve──▶ RESOLVED/REJECTED
                                              │
                                              └─ (buyer accepts seller response) ─▶ RESOLVED
```

## Dispute Reasons

- `ITEM_NOT_AS_DESCRIBED` - barang tidak sesuai deskripsi
- `DAMAGED` - barang rusak saat diterima
- `NOT_RECEIVED` - barang tidak diterima
- `WRONG_ITEM` - barang salah
- `OTHER` - lainnya

## Endpoints

### POST /disputes
Buka dispute baru (buyer).

```json
{
  "order_id": "uuid",
  "order_item_id": "uuid-optional",
  "reason": "ITEM_NOT_AS_DESCRIBED",
  "description": "Warna tidak sesuai, saya pesan hitam dapat putih",
  "evidence_files": ["https://..."],
  "requested_refund_amount": 1500000
}
```

Validasi: max 5 evidence files, 1 dispute OPEN per order.

### GET /disputes
List disputes (buyer: miliknya; seller: dimana dia seller; admin: semua).

### GET /disputes/{id}
Get detail dispute + messages thread.

### POST /disputes/{id}/seller-response
Seller respond ke dispute.

```json
{
  "message": "Mohon maaf atas ketidaknyamanan, kami akan ganti dengan warna hitam",
  "proposed_resolution": "OFFER_REPLACE",
  "proposed_amount": null
}
```

Resolutions: `ACCEPT_REFUND`, `REJECT`, `OFFER_PARTIAL`, `OFFER_REPLACE`

### POST /disputes/{id}/escalate
Buyer escalate ke admin (jika tidak puas dengan seller response).

```json
{ "reason": "Seller tidak responsive" }
```

### POST /disputes/{id}/messages
Add message ke dispute thread.

### POST /admin/disputes/{id}/resolve
Admin resolve dispute.

```json
{
  "resolution": "FULL_REFUND",
  "refund_amount": 1500000,
  "note": "Bukti foto mendukung klaim buyer"
}
```

Resolutions: `FULL_REFUND`, `PARTIAL_REFUND`, `REPLACE`, `REJECT`

## SLA

- **Seller response**: 48 jam sejak dispute dibuka. Jika lewat → buyer bisa auto-escalate.
- **Admin resolution**: 7 hari sejak escalated.
- **Dispute window**: 7 hari sejak order delivered (buyer tidak bisa dispute setelah ini).
