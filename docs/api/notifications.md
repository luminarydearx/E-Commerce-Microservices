# Notifications API (Notification Service)

> Service: `notification-service` (Python/FastAPI)  
> Base URL: `http://localhost:8080/api/v1`  
> Port: `8005`

Multi-channel notifications: email, push, in-app. Async via Kafka consumer.

## Channels

- **email** - SMTP via aiosmtplib
- **push** - FCM (Android) / APNs (iOS) - planned
- **in_app** - Stored in DB, retrieved via API
- **whatsapp** - WhatsApp Business API - planned

## Event-Driven

Notification service consume events dari Kafka:
- `ecommerce.user.events` - user.registered → welcome email
- `ecommerce.order.events` - order.created → order confirmation email
- `ecommerce.payment.events` - payment.succeeded/failed → receipt email

## Endpoints

### POST /internal/send
Internal: Direct send notification (untuk service yang tidak pakai Kafka).

```json
{
  "channel": "email",
  "to": "user@example.com",
  "subject": "Welcome!",
  "template": "welcome.html",
  "context": {"name": "John Doe"}
}
```

### GET /notifications
List in-app notifications untuk user (planned).

### PATCH /notifications/{id}/read
Mark notification as read (planned).

## Templates

Email templates pakai Jinja2 dengan autoescape (XSS protection). Lokasi: `app/templates/`.

Available templates:
- `welcome.html` - Welcome email after registration
- `order_created.html` - Order confirmation
- `payment_success.html` - Payment receipt
- `payment_failed.html` - Payment failure notification

## Retry Policy

Pakai tenacity dengan exponential backoff:
- Max 3 retries
- Wait: 2s, 4s, 8s
- Jika semua gagal → log error + write to retry queue (planned)
