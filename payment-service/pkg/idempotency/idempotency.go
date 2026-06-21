package idempotency

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

type Manager struct {
	redis *redis.Client
	ttl   time.Duration
}

func New(rdb *redis.Client) *Manager {
	return &Manager{redis: rdb, ttl: 24 * time.Hour}
}

type Result struct {
	Status int             `json:"status"`
	Body   json.RawMessage `json:"body"`
}

// Get returns cached response if exists
func (m *Manager) Get(ctx context.Context, key string) (*Result, error) {
	if key == "" {
		return nil, nil
	}
	if _, err := uuid.Parse(key); err != nil {
		return nil, err
	}
	val, err := m.redis.Get(ctx, "idem:"+key).Result()
	if err != nil {
		return nil, nil
	}
	var r Result
	if err := json.Unmarshal([]byte(val), &r); err != nil {
		return nil, err
	}
	return &r, nil
}

// Set stores response for idempotency key
func (m *Manager) Set(ctx context.Context, key string, status int, body []byte) error {
	if key == "" {
		return nil
	}
	r := Result{Status: status, Body: body}
	data, _ := json.Marshal(r)
	return m.redis.Set(ctx, "idem:"+key, data, m.ttl).Err()
}
