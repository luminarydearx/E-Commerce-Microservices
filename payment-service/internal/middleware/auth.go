package middleware

import (
	"context"
	"net/http"
	"strings"
	"time"

	"ecommerce/payment-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// Authenticate verifies JWT from API Gateway header
func Authenticate(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		uid := c.GetHeader("X-User-Id")
		if uid != "" {
			if _, err := uuid.Parse(uid); err != nil {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid user_id header"})
				return
			}
			c.Set("user_id", uid)
			roles := c.GetHeader("X-User-Roles")
			if roles != "" {
				c.Set("user_roles", strings.Split(roles, ","))
			}
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "must go through API gateway"})
	}
}

func InternalOnly(expectedToken string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if expectedToken == "" {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "internal endpoints disabled"})
			return
		}
		token := c.GetHeader("X-Internal-Token")
		if token != expectedToken {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "forbidden"})
			return
		}
		c.Next()
	}
}

// IdempotencyRequired for payment endpoints
func IdempotencyRequired(log *logger.Logger, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Method != http.MethodPost && c.Request.Method != http.MethodPut {
			c.Next()
			return
		}
		path := c.FullPath()
		if !strings.Contains(path, "/payments") && !strings.Contains(path, "/withdrawals") {
			c.Next()
			return
		}
		key := c.GetHeader("Idempotency-Key")
		if key == "" {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
				"error":   "missing_idempotency_key",
				"message": "Idempotency-Key header required for this operation",
			})
			return
		}
		if _, err := uuid.Parse(key); err != nil {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
				"error":   "invalid_idempotency_key",
				"message": "Idempotency-Key must be a UUID",
			})
			return
		}

		ctx, cancel := context.WithTimeout(c.Request.Context(), 500*time.Millisecond)
		defer cancel()
		redisKey := "idem:" + key
		val, err := rdb.Get(ctx, redisKey).Result()
		if err == nil {
			log.Info("idempotency cache hit", "key", key)
			c.Header("X-Idempotent-Replay", "true")
			c.Data(http.StatusOK, "application/json", []byte(val))
			c.Abort()
			return
		}
		c.Set("idempotency_key", key)
		c.Next()

		if c.Writer.Status() < 400 {
			_ = rdb.Set(ctx, redisKey, `{"status":"completed"}`, 24*time.Hour).Err()
		}
	}
}
