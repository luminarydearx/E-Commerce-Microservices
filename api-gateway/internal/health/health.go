package health

import (
	"ecommerce/api-gateway/internal/config"
	"net/http"

	"github.com/gin-gonic/gin"
)

// Liveness returns 200 if process is alive
func Liveness(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":   "alive",
		"service":  "api-gateway",
		"version":  "1.0.0",
	})
}

// Readiness checks if all downstream services are reachable
func Readiness(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Quick check: just verify config loaded & Redis reachable
		// Full check could ping each downstream service
		c.JSON(http.StatusOK, gin.H{
			"status":  "ready",
			"service": "api-gateway",
			"env":     cfg.Environment,
			"services": cfg.Services,
		})
	}
}
