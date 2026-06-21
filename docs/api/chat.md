# Chat API (Chat Service)

> Service: `chat-service` (Go + WebSocket)  
> Base URL: `ws://localhost:8080/ws/chat` (WebSocket), `http://localhost:8080/api/v1/chat` (REST)  
> Port: `8014`

Real-time chat antara buyer ↔ seller, dengan message persistence.

## WebSocket Connection

```
GET /ws/chat
Headers:
  X-User-Id: <uuid>
  X-User-Roles: buyer,seller
```

### Client → Server messages

**Join conversation:**
```json
{
  "type": "join",
  "conversation_id": "uuid"
}
```

**Send message:**
```json
{
  "type": "text",
  "conversation_id": "uuid",
  "content": "Apakah ini masih ready?"
}
```

**Message types:** `text`, `image`, `product_card`, `system`, `join`, `leave`

### Server → Client messages
Broadcast ke semua client dalam conversation yang sama.

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "sender_id": "uuid",
  "sender_role": "buyer",
  "content": "Apakah ini masih ready?",
  "type": "text",
  "created_at": "2026-06-21T10:00:00Z"
}
```

### Heartbeat
Server kirim ping setiap 30 detik. Client harus response pong dalam 60 detik atau di-disconnect.

## REST Endpoints

### GET /chat/conversations
List conversations user (sebagai buyer atau seller).

```json
{
  "data": [
    {
      "id": "uuid",
      "buyer_id": "uuid",
      "seller_id": "uuid",
      "product_id": "uuid",
      "last_message": "2026-06-21T10:00:00Z",
      "unread_count": 3,
      "created_at": "..."
    }
  ]
}
```

### POST /chat/conversations
Create conversation baru dengan seller untuk product tertentu.

```json
{
  "seller_id": "uuid",
  "product_id": "uuid"
}
```

Jika sudah ada conversation dengan seller & product yang sama → return existing.

### GET /chat/conversations/{id}/messages
Get history messages (max 100, dengan pagination).

### PATCH /chat/conversations/{id}/read
Mark conversation as read (reset unread_count).

### DELETE /chat/conversations/{id}
Soft delete conversation (hide dari list user, masih ada di DB).

## Features

- **1 conversation per (buyer, seller, product)**: unique constraint
- **Cannot chat with self**: DB constraint
- **Online status**: hub tracks active connections
- **Message persistence**: semua message disimpan di PostgreSQL
- **Auto-reconnect**: client harus handle disconnect & reconnect
