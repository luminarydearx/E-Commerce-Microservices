package middleware

import (
	"fmt"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"ecommerce/order-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
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

func CorrelationID() gin.HandlerFunc {
	return func(c *gin.Context) {
		cid := c.GetHeader("X-Correlation-Id")
		if cid == "" {
			cid = c.GetString("request_id")
		}
		c.Set("correlation_id", cid)
		c.Writer.Header().Set("X-Correlation-Id", cid)
		c.Next()
	}
}

func SecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Header("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
		c.Header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
		c.Next()
	}
}

func CORS(allowedOrigins []string) gin.HandlerFunc {
	allowed := make(map[string]bool)
	for _, o := range allowedOrigins {
		allowed[o] = true
	}
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if origin != "" && allowed[origin] {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-Id, X-Correlation-Id, Idempotency-Key")
			c.Header("Access-Control-Allow-Credentials", "true")
		}
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

func Recovery(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				stack := string(debug.Stack())
				log.Error("panic recovered", fmt.Errorf("%v", r),
					"path", c.Request.URL.Path, "stack", stack)
				c.AbortWithStatusJSON(500, gin.H{
					"error":   "internal_error",
					"message": "an unexpected error occurred",
				})
			}
		}()
		c.Next()
	}
}

func Logger(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		duration := time.Since(start)
		status := c.Writer.Status()

		fields := []any{
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
			"status", status,
			"duration_ms", duration.Milliseconds(),
			"ip", c.ClientIP(),
			"request_id", c.GetString("request_id"),
			"correlation_id", c.GetString("correlation_id"),
		}
		if uid, ok := c.Get("user_id"); ok {
			fields = append(fields, "user_id", uid)
		}
		if len(c.Errors) > 0 {
			errs := make([]string, 0, len(c.Errors))
			for _, e := range c.Errors {
				errs = append(errs, e.Error())
			}
			fields = append(fields, "errors", strings.Join(errs, "; "))
		}

		if status >= 500 {
			log.Error("request completed with server error", nil, fields...)
		} else if status >= 400 {
			log.Warn("request completed with client error", fields...)
		} else {
			log.Info("request completed", fields...)
		}
	}
}
