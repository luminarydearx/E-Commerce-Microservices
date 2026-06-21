package middleware

import (
	"context"
	"net/http"
	"strings"
	"time"

	"ecommerce/shipping-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-Id")
		if rid == "" {
			rid = uuid.NewString()
		}
		c.Set("request_id", rid)
		c.Writer.Header().Set("X-Request-Id", rid)
		c.Next()
	}
}

func Logger(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		dur := time.Since(start)
		status := c.Writer.Status()
		fields := []any{
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
			"status", status,
			"duration_ms", dur.Milliseconds(),
			"request_id", c.GetString("request_id"),
		}
		if status >= 500 {
			log.Error("request", nil, fields...)
		} else if status >= 400 {
			log.Warn("request", fields...)
		} else {
			log.Info("request", fields...)
		}
	}
}

func Recovery(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				log.Error("panic", nil, "error", r, "path", c.Request.URL.Path)
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
		c.Header("Strict-Transport-Security", "max-age=31536000")
		c.Next()
	}
}

func Authenticate() gin.HandlerFunc {
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
			c.Set("user_roles", strings.Split(roles, ","))
		}
		c.Next()
	}
}

func AdminOnly() gin.HandlerFunc {
	return func(c *gin.Context) {
		rolesAny, _ := c.Get("user_roles")
		roles, _ := rolesAny.([]string)
		for _, r := range roles {
			if r == "admin" || r == "superadmin" {
				c.Next()
				return
			}
		}
		c.AbortWithStatusJSON(403, gin.H{"error": "admin_required"})
	}
}

func InternalOnly(expectedToken string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if expectedToken == "" {
			c.AbortWithStatusJSON(403, gin.H{"error": "internal_disabled"})
			return
		}
		if c.GetHeader("X-Internal-Token") != expectedToken {
			c.AbortWithStatusJSON(403, gin.H{"error": "forbidden"})
			return
		}
		c.Next()
	}
}

var _ = redis.NewClient
var _ = context.Background
