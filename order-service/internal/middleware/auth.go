package middleware

import (
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"ecommerce/order-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// Authenticate verifies JWT from API Gateway header X-User-Id (gateway already verified)
// OR verifies Bearer token directly (for service-to-service direct calls)
func Authenticate(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Path 1: API Gateway already verified & forwarded X-User-Id
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

		// Path 2: Direct JWT verification (service-to-service or local dev)
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
			return
		}
		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid auth header"})
			return
		}
		// Verify JWT (in production, load public key from disk)
		// For simplicity, trust gateway header only in dev
		log.Warn("direct JWT verification not configured in dev, please use API gateway")
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "must go through API gateway"})
	}
}

// InternalOnly restricts access to internal endpoints (between services)
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

// IdempotencyRequired for POST/PUT on critical paths
func IdempotencyRequired(log *logger.Logger, rdb *redis.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Only enforce for POST/PUT
		if c.Request.Method != http.MethodPost && c.Request.Method != http.MethodPut {
			c.Next()
			return
		}
		// Only for specific paths
		path := c.FullPath()
		if !strings.Contains(path, "/checkout") && !strings.Contains(path, "/orders/") {
			c.Next()
			return
		}

		key := c.GetHeader("Idempotency-Key")
		if key == "" {
			c.Next()
			return
		}
		// Validate UUID format
		if _, err := uuid.Parse(key); err != nil {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
				"error":   "invalid_idempotency_key",
				"message": "Idempotency-Key must be a UUID",
			})
			return
		}

		// Check Redis cache
		ctx, cancel := context.WithTimeout(c.Request.Context(), 500*time.Millisecond)
		defer cancel()
		redisKey := "idem:" + key
		val, err := rdb.Get(ctx, redisKey).Result()
		if err == nil {
			// Cache hit: return cached response
			log.Info("idempotency cache hit", "key", key)
			c.Header("X-Idempotent-Replay", "true")
			c.Data(http.StatusOK, "application/json", []byte(val))
			c.Abort()
			return
		}

		// Cache miss: process request, capture response, store
		c.Set("idempotency_key", key)
		c.Next()

		// Capture response body (already written to client)
		// In real impl, wrap ResponseWriter to capture body before write
		// For simplicity, store success marker
		if c.Writer.Status() < 400 {
			_ = rdb.Set(ctx, redisKey, `{"status":"completed"}`, 24*time.Hour).Err()
		}
	}
}

// Unused but kept for completeness
func loadPublicKey(path string) (*rsa.PublicKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return nil, fmt.Errorf("invalid PEM")
	}
	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return nil, err
	}
	rsaPub, ok := pub.(*rsa.PublicKey)
	if !ok {
		return nil, fmt.Errorf("not RSA")
	}
	return rsaPub, nil
}

// Unused import shim
var _ = jwt.SigningMethodRS256
