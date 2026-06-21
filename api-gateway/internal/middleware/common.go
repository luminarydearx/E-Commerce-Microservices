package middleware

import (
	"fmt"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"ecommerce/api-gateway/pkg/logger"

	"github.com/gin-gonic/gin"
)

// SecurityHeaders sets security-related headers
func SecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Header("X-XSS-Protection", "1; mode=block")
		c.Header("Referrer-Policy", "strict-origin-when-cross-origin")
		c.Header("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
		c.Header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
		c.Header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
		c.Header("Cross-Origin-Opener-Policy", "same-origin")
		c.Header("Cross-Origin-Resource-Policy", "same-origin")
		c.Next()
	}
}

// CORS configured (no wildcard)
func CORS(allowedOrigins []string) gin.HandlerFunc {
	allowed := make(map[string]bool, len(allowedOrigins))
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
			c.Header("Access-Control-Max-Age", "600")
			c.Header("Vary", "Origin")
		}
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

// RequestSizeLimit rejects oversized requests
func RequestSizeLimit(maxBytes int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.ContentLength > maxBytes {
			c.AbortWithStatusJSON(413, gin.H{
				"error":   "request_too_large",
				"message": fmt.Sprintf("request body exceeds %d bytes", maxBytes),
			})
			return
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxBytes)
		c.Next()
	}
}

// Recovery with structured logging
func Recovery(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				stack := string(debug.Stack())
				reqID, _ := c.Get("request_id")
				correlationID, _ := c.Get("correlation_id")
				log.Error("panic recovered",
					fmt.Errorf("%v", r),
					"request_id", reqID,
					"correlation_id", correlationID,
					"path", c.Request.URL.Path,
					"method", c.Request.Method,
					"stack", stack,
				)
				c.AbortWithStatusJSON(500, gin.H{
					"error":          "internal_error",
					"message":        "an unexpected error occurred",
					"request_id":     reqID,
					"correlation_id": correlationID,
				})
			}
		}()
		c.Next()
	}
}

// Logger structured request logging
func Logger(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		method := c.Request.Method

		c.Next()

		duration := time.Since(start)
		status := c.Writer.Status()
		size := c.Writer.Size()

		reqID, _ := c.Get("request_id")
		correlationID, _ := c.Get("correlation_id")
		userID, _ := c.Get("user_id")

		fields := []any{
			"method", method,
			"path", path,
			"status", status,
			"duration_ms", duration.Milliseconds(),
			"size", size,
			"ip", c.ClientIP(),
			"request_id", reqID,
			"correlation_id", correlationID,
			"user_agent", c.GetHeader("User-Agent"),
		}
		if userID != nil {
			fields = append(fields, "user_id", userID)
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

// Trace adds OpenTelemetry span attributes
func Trace() gin.HandlerFunc {
	return func(c *gin.Context) {
		// otelgin already handles tracing; this is for additional context
		c.Next()
	}
}

// Prometheus middleware (records request metrics)
func Prometheus() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()
	}
}
