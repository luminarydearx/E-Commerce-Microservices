package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"ecommerce/chat-service/internal/config"
	"ecommerce/chat-service/internal/hub"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/jackc/pgx/v5/pgxpool"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		// In production: check origin against allowlist
		return true
	},
}

type Handler struct {
	hub  *hub.Hub
	cfg  *config.Config
	pool *pgxpool.Pool
}

func NewHandler(h *hub.Hub, cfg *config.Config) *Handler {
	pool, err := pgxpool.New(context.Background(), cfg.DatabaseURL)
	if err != nil {
		// Continue without DB for now (degraded mode)
		fmt.Printf("warning: db connection failed: %v\n", err)
	}
	return &Handler{hub: h, cfg: cfg, pool: pool}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(200, gin.H{"status": "alive", "service": "chat-service"})
}

func (h *Handler) Authenticate() gin.HandlerFunc {
	return func(c *gin.Context) {
		uid := c.GetHeader("X-User-Id")
		if uid == "" {
			c.AbortWithStatusJSON(401, gin.H{"error": "unauthorized"})
			return
		}
		if _, err := uuid.Parse(uid); err != nil {
			c.AbortWithStatusJSON(401, gin.H{"error": "invalid_user"})
			return
		}
		c.Set("user_id", uid)
		roles := c.GetHeader("X-User-Roles")
		if roles != "" {
			c.Set("user_roles", roles)
		}
		c.Next()
	}
}

func (h *Handler) HandleWebSocket(c *gin.Context) {
	uid := c.GetString("user_id")
	roles := c.GetString("user_roles")

	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		c.AbortWithStatusJSON(500, gin.H{"error": "ws_upgrade_failed"})
		return
	}

	client := &hub.Client{
		ID:            uuid.New().String(),
		UserID:        uid,
		UserRole:      roles,
		Conversations: make(map[string]bool),
		Hub:           h.hub,
		Send:          make(chan []byte, 256),
	}
	h.hub.Register(client)

	// Read & write goroutines
	go h.writePump(conn, client)
	go h.readPump(conn, client)
}

func (h *Handler) readPump(conn *websocket.Conn, client *hub.Client) {
	defer func() {
		h.hub.Unregister(client)
		conn.Close()
	}()
	conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		return nil
	})
	for {
		_, message, err := conn.ReadMessage()
		if err != nil {
			break
		}
		// Parse incoming message
		var msg hub.Message
		if err := json.Unmarshal(message, &msg); err != nil {
			continue
		}
		msg.SenderID = client.UserID
		msg.SenderRole = client.UserRole

		// Join conversation command
		if msg.Type == "join" {
			h.hub.JoinConversation(client.UserID, msg.ConversationID)
			continue
		}
		if msg.Type == "leave" {
			h.hub.LeaveConversation(client.UserID, msg.ConversationID)
			continue
		}

		// Broadcast to conversation
		h.hub.Broadcast(msg.ConversationID, &msg)

		// Persist to DB (best-effort)
		if h.pool != nil {
			go h.persistMessage(&msg)
		}
	}
}

func (h *Handler) writePump(conn *websocket.Conn, client *hub.Client) {
	ticker := time.NewTicker(30 * time.Second)
	defer func() {
		ticker.Stop()
		conn.Close()
	}()
	for {
		select {
		case message, ok := <-client.Send:
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if !ok {
				conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, message); err != nil {
				return
			}
		case <-ticker.C:
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func (h *Handler) persistMessage(msg *hub.Message) {
	if h.pool == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, err := h.pool.Exec(ctx, `
		INSERT INTO chat.messages (id, conversation_id, sender_id, sender_role, content, type, metadata, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
	`, msg.ID, msg.ConversationID, msg.SenderID, msg.SenderRole, msg.Content, msg.Type, msg.Metadata, msg.CreatedAt)
	if err != nil {
		fmt.Printf("persist message error: %v\n", err)
	}
}

// REST endpoints

func (h *Handler) ListConversations(c *gin.Context) {
	uid := c.GetString("user_id")
	if h.pool == nil {
		c.JSON(200, gin.H{"data": []any{}})
		return
	}
	rows, err := h.pool.Query(c.Request.Context(), `
		SELECT id, buyer_id, seller_id, product_id, last_message_at, buyer_unread, seller_unread, created_at
		FROM chat.conversations
		WHERE buyer_id = $1 OR seller_id = $1
		ORDER BY last_message_at DESC NULLS LAST
		LIMIT 50
	`, uid)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	defer rows.Close()

	conversations := []map[string]any{}
	for rows.Next() {
		var id, buyerID, sellerID string
		var productID *string
		var lastMsgAt *time.Time
		var buyerUnread, sellerUnread int
		var createdAt time.Time
		_ = rows.Scan(&id, &buyerID, &sellerID, &productID, &lastMsgAt, &buyerUnread, &sellerUnread, &createdAt)
		unread := buyerUnread
		if uid == sellerID {
			unread = sellerUnread
		}
		conversations = append(conversations, map[string]any{
			"id":            id,
			"buyer_id":      buyerID,
			"seller_id":     sellerID,
			"product_id":    productID,
			"last_message":  lastMsgAt,
			"unread_count":  unread,
			"created_at":    createdAt,
		})
	}
	c.JSON(200, gin.H{"data": conversations, "total": len(conversations)})
}

func (h *Handler) GetMessages(c *gin.Context) {
	conversationID := c.Param("id")
	if conversationID == "" {
		c.JSON(400, gin.H{"error": "conversation_id required"})
		return
	}
	if h.pool == nil {
		c.JSON(200, gin.H{"data": []any{}})
		return
	}
	rows, err := h.pool.Query(c.Request.Context(), `
		SELECT id, conversation_id, sender_id, sender_role, content, type, metadata, created_at
		FROM chat.messages
		WHERE conversation_id = $1
		ORDER BY created_at ASC
		LIMIT 100
	`, conversationID)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	defer rows.Close()

	messages := []map[string]any{}
	for rows.Next() {
		var id, convID, senderID, senderRole, content, msgType string
		var metadata map[string]any
		var createdAt time.Time
		_ = rows.Scan(&id, &convID, &senderID, &senderRole, &content, &msgType, &metadata, &createdAt)
		messages = append(messages, map[string]any{
			"id":              id,
			"conversation_id": convID,
			"sender_id":       senderID,
			"sender_role":     senderRole,
			"content":         content,
			"type":            msgType,
			"metadata":        metadata,
			"created_at":      createdAt,
		})
	}
	c.JSON(200, gin.H{"data": messages, "total": len(messages)})
}

func (h *Handler) CreateConversation(c *gin.Context) {
	uid := c.GetString("user_id")
	var req struct {
		SellerID  string `json:"seller_id"`
		ProductID string `json:"product_id"`
	}
	body, _ := io.ReadAll(c.Request.Body)
	if err := json.Unmarshal(body, &req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}
	if req.SellerID == "" {
		c.JSON(400, gin.H{"error": "seller_id required"})
		return
	}
	if uid == req.SellerID {
		c.JSON(400, gin.H{"error": "cannot_chat_with_self"})
		return
	}

	if h.pool == nil {
		c.JSON(503, gin.H{"error": "db_unavailable"})
		return
	}

	// Check existing conversation
	var existingID string
	err := h.pool.QueryRow(c.Request.Context(), `
		SELECT id FROM chat.conversations
		WHERE buyer_id = $1 AND seller_id = $2 AND (product_id = $3 OR product_id IS NULL)
		ORDER BY created_at DESC LIMIT 1
	`, uid, req.SellerID, req.ProductID).Scan(&existingID)

	if err == nil {
		c.JSON(200, gin.H{"id": existingID, "exists": true})
		return
	}

	convID := uuid.New().String()
	_, err = h.pool.Exec(c.Request.Context(), `
		INSERT INTO chat.conversations (id, buyer_id, seller_id, product_id)
		VALUES ($1, $2, $3, $4)
	`, convID, uid, req.SellerID, req.ProductID)
	if err != nil {
		c.JSON(500, gin.H{"error": "create_failed"})
		return
	}
	c.JSON(201, gin.H{"id": convID, "exists": false})
}

func (h *Handler) MarkRead(c *gin.Context) {
	convID := c.Param("id")
	uid := c.GetString("user_id")
	if h.pool == nil {
		c.Status(204)
		return
	}
	_, err := h.pool.Exec(c.Request.Context(), `
		UPDATE chat.conversations
		SET buyer_unread = CASE WHEN buyer_id = $1 THEN 0 ELSE buyer_unread END,
		    seller_unread = CASE WHEN seller_id = $1 THEN 0 ELSE seller_unread END
		WHERE id = $2
	`, uid, convID)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	c.Status(204)
}

func (h *Handler) DeleteConversation(c *gin.Context) {
	convID := c.Param("id")
	uid := c.GetString("user_id")
	if h.pool == nil {
		c.Status(204)
		return
	}
	_, _ = h.pool.Exec(c.Request.Context(), `
		UPDATE chat.conversations SET is_deleted = TRUE WHERE id = $1 AND (buyer_id = $2 OR seller_id = $2)
	`, convID, uid)
	c.Status(204)
}

// Middleware
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-Id")
		if rid == "" {
			rid = uuid.New().String()
		}
		c.Set("request_id", rid)
		c.Writer.Header().Set("X-Request-Id", rid)
		c.Next()
	}
}

func Logger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		fmt.Printf("[%s] %s %s %d %dms\n",
			c.GetString("request_id"), c.Request.Method, c.Request.URL.Path,
			c.Writer.Status(), time.Since(start).Milliseconds())
	}
}

func Recovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				c.AbortWithStatusJSON(500, gin.H{"error": "internal_error"})
			}
		}()
		c.Next()
	}
}

func SecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Next()
	}
}
