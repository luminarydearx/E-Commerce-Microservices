# Addresses API (Address Service)

> Service: `address-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8011`

Multiple addresses per user, primary address, geocoding via Google Maps.

## Endpoints

### GET /addresses
List semua alamat user.

### POST /addresses
Tambah alamat baru.

```json
{
  "label": "Rumah",
  "recipient_name": "John Doe",
  "recipient_phone": "+6281234567890",
  "address_line1": "Jl. Sudirman No. 1",
  "address_line2": "Gang Mangga 2",
  "province": "DKI Jakarta",
  "city": "Jakarta Pusat",
  "district": "Menteng",
  "subdistrict": "Gondangdia",
  "postal_code": "10350",
  "latitude": -6.2088,
  "longitude": 106.8456,
  "is_primary": true,
  "notes": "Pagar warna hijau"
}
```

Limit: max 10 alamat per user.

### GET /addresses/{id}
Get detail alamat.

### PUT /addresses/{id}
Update alamat.

### DELETE /addresses/{id}
Hapus alamat. Jika hapus alamat primary, alamat terbaru yang lain otomatis jadi primary.

### PATCH /addresses/{id}/set-primary
Set alamat sebagai primary (unset alamat lain).

### POST /addresses/geocode
Geocode address string ke lat/lng via Google Maps API.

```json
{ "address": "Jl. Sudirman No. 1, Jakarta" }
```

Response: latitude, longitude, formatted_address.
