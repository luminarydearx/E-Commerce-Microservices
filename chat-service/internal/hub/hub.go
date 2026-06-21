package hub

import (
	"encoding/json"
	"sync"
	"time"

	"github.com/google/uuid"
)

// Client represents a connected WebSocket client
type Client struct {
	ID         string
	UserID     string
	UserRole   string
	Conversations map[string]bool // conversation IDs this client is in
	Hub        *Hub
	Send       chan []byte
}

// Message represents a chat message
type Message struct {
	ID             string `json:"id"`
	ConversationID string `json:"conversation_id"`
	SenderID       string `json:"sender_id"`
	SenderRole     string `json:"sender_role"`
	Content        string `json:"content"`
	Type           string `json:"type"` // text, image, product_card, system
	Metadata       map[string]any `json:"metadata,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

// Hub maintains active clients and broadcasts messages
type Hub struct {
	clients    map[string]*Client // userID -> Client (1 client per user for simplicity)
	register   chan *Client
	unregister chan *Client
	broadcast  chan *BroadcastMsg
	mu         sync.RWMutex
}

type BroadcastMsg struct {
	ConversationID string
	Message        *Message
}

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[string]*Client),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		broadcast:  make(chan *BroadcastMsg, 256),
	}
}

func (h *Hub) Run() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			// Close existing client for this user
			if existing, ok := h.clients[client.UserID]; ok {
				close(existing.Send)
				delete(h.clients, existing.UserID)
			}
			h.clients[client.UserID] = client
			h.mu.Unlock()
		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client.UserID]; ok {
				if client == h.clients[client.UserID] {
					delete(h.clients, client.UserID)
					close(client.Send)
				}
			}
			h.mu.Unlock()
		case msg := <-h.broadcast:
			// In production: lookup participants for conversation_id
			// For now: broadcast to all clients in that conversation
			data, _ := json.Marshal(msg.Message)
			h.mu.RLock()
			for _, client := range h.clients {
				if client.Conversations[msg.ConversationID] {
					select {
					case client.Send <- data:
					default:
						// Buffer full, skip (will be picked up by retry)
					}
				}
			}
			h.mu.RUnlock()
		case <-ticker.C:
			// Heartbeat / cleanup
		}
	}
}

func (h *Hub) Register(client *Client) {
	h.register <- client
}

func (h *Hub) Unregister(client *Client) {
	h.unregister <- client
}

func (h *Hub) Broadcast(conversationID string, msg *Message) {
	if msg.ID == "" {
		msg.ID = uuid.New().String()
	}
	if msg.CreatedAt.IsZero() {
		msg.CreatedAt = time.Now()
	}
	h.broadcast <- &BroadcastMsg{ConversationID: conversationID, Message: msg}
}

func (h *Hub) IsUserOnline(userID string) bool {
	h.mu.RLock()
	defer h.mu.RUnlock()
	_, ok := h.clients[userID]
	return ok
}

func (h *Hub) GetOnlineUsers() []string {
	h.mu.RLock()
	defer h.mu.RUnlock()
	users := make([]string, 0, len(h.clients))
	for uid := range h.clients {
		users = append(users, uid)
	}
	return users
}

func (h *Hub) JoinConversation(userID, conversationID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if client, ok := h.clients[userID]; ok {
		client.Conversations[conversationID] = true
	}
}

func (h *Hub) LeaveConversation(userID, conversationID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if client, ok := h.clients[userID]; ok {
		delete(client.Conversations, conversationID)
	}
}
