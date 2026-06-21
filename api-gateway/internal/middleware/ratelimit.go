package middleware

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"ecommerce/api-gateway/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// RedisRateLimiter token bucket implementation backed by Redis
type RedisRateLimiter struct {
	client *redis.Client
	log    *logger.Logger
}

func NewRedisRateLimiter(redisURL string, log *logger.Logger) (*RedisRateLimiter, error) {
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}
	client := redis.NewClient(opt)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}
	return &RedisRateLimiter{client: client, log: log}, nil
}

func (r *RedisRateLimiter) Close() error {
	return r.client.Close()
}

// Allow checks if a key is allowed under rate limit using token bucket
// Lua script for atomic check (prevents race condition)
const luaScript = `
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = burst
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
local refill = elapsed * rate / 1000
tokens = math.min(burst, tokens + refill)

local allowed = 0
local remaining = tokens
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
    remaining = tokens
end

redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, ttl)

return {allowed, remaining}
`

// Allow checks rate limit for a key, returns (allowed, remaining, retryAfter)
func (r *RedisRateLimiter) Allow(ctx context.Context, key string, rate, burst int) (bool, int, time.Duration) {
	now := time.Now().UnixMilli()
	ttl := 3600 // 1 hour
	res, err := r.client.Eval(ctx, luaScript, []string{key},
		rate, burst, now, ttl).Result()
	if err != nil {
		// Fail open on Redis error to prevent total outage, but log it
		r.log.Error("rate limiter redis error", err, "key", key)
		return true, burst, 0
	}
	vals, ok := res.([]any)
	if !ok || len(vals) != 2 {
		return true, burst, 0
	}
	allowed, _ := vals[0].(int64)
	remaining, _ := vals[1].(int64)
	if allowed == 1 {
		return true, int(remaining), 0
	}
	// Calculate retry-after based on rate
	retryAfter := time.Duration(1000/rate) * time.Millisecond
	if retryAfter < time.Second {
		retryAfter = time.Second
	}
	return false, int(remaining), retryAfter
}

// RateLimit applies global + per-user rate limit
func RateLimit(rl *RedisRateLimiter, cfg RateLimitConfig) gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()
		// Global IP-based limit
		key := "rl:global:" + ip
		allowed, remaining, retry := rl.Allow(c.Request.Context(), key, cfg.GlobalRPS, cfg.GlobalBurst)
		if !allowed {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "rate_limit_exceeded",
				"message": "too many requests, please slow down",
			})
			c.Header("Retry-After", strconv.Itoa(int(retry.Seconds())))
			c.Header("X-RateLimit-Remaining", "0")
			return
		}
		c.Header("X-RateLimit-Remaining", strconv.Itoa(remaining))

		// Per-user limit if authenticated
		userID, exists := c.Get("user_id")
		if exists {
			uid, _ := userID.(string)
			if uid != "" {
				key = "rl:user:" + uid
				allowed, remaining, retry = rl.Allow(c.Request.Context(), key, cfg.PerUserRPS, cfg.PerUserBurst)
				if !allowed {
					c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
						"error":   "rate_limit_exceeded",
						"message": "per-user rate limit exceeded",
					})
					c.Header("Retry-After", strconv.Itoa(int(retry.Seconds())))
					c.Header("X-RateLimit-Remaining", "0")
					return
				}
				c.Header("X-RateLimit-Remaining", strconv.Itoa(remaining))
			}
		}

		c.Next()
	}
}

// RateLimitPublic applies rate limit for public endpoints (auth, register, etc.)
func RateLimitPublic(rl *RedisRateLimiter, cfg RateLimitConfig) gin.HandlerFunc {
	return func(c *gin.Context) {
		ip := c.ClientIP()
		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}

		// Apply stricter limit for auth endpoints
		var rate, burst int
		if strings.Contains(path, "/auth/") {
			rate = cfg.AuthRPS
			burst = cfg.AuthBurst
		} else {
			rate = cfg.PublicRPS
			burst = cfg.PublicBurst
		}

		key := fmt.Sprintf("rl:public:%s:%s", ip, path)
		allowed, remaining, retry := rl.Allow(c.Request.Context(), key, rate, burst)
		if !allowed {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":   "rate_limit_exceeded",
				"message": "too many requests",
			})
			c.Header("Retry-After", strconv.Itoa(int(retry.Seconds())))
			c.Header("X-RateLimit-Remaining", "0")
			return
		}
		c.Header("X-RateLimit-Remaining", strconv.Itoa(remaining))
		c.Next()
	}
}
