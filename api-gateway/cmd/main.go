package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ecommerce/api-gateway/internal/config"
	"ecommerce/api-gateway/internal/handler"
	"ecommerce/api-gateway/internal/health"
	"ecommerce/api-gateway/internal/middleware"
	"ecommerce/api-gateway/pkg/logger"
	"ecommerce/api-gateway/pkg/tracing"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}

	log, err := logger.New(cfg.Environment)
	if err != nil {
		panic(err)
	}
	defer log.Sync()

	// Init OpenTelemetry tracer
	shutdownTracer, err := tracing.InitTracer(cfg.ServiceName, cfg.OtelEndpoint)
	if err != nil {
		log.Fatal("failed to init tracer", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdownTracer(ctx)
	}()

	// Init dependencies
	rateLimiter, err := middleware.NewRedisRateLimiter(cfg.RedisURL, log)
	if err != nil {
		log.Fatal("failed to init rate limiter", err)
	}
	defer rateLimiter.Close()

	authVerifier, err := middleware.NewJWTVerifier(cfg.JWT.PublicKeyPath, log)
	if err != nil {
		log.Fatal("failed to init auth verifier", err)
	}

	proxy, err := handler.NewReverseProxy(cfg, log)
	if err != nil {
		log.Fatal("failed to init proxy", err)
	}

	// Setup Gin
	if cfg.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()

	// Global middleware
	r.Use(middleware.RequestID())
	r.Use(middleware.CorrelationID())
	r.Use(middleware.Logger(log))
	r.Use(middleware.Recovery(log))
	r.Use(middleware.SecurityHeaders())
	r.Use(middleware.CORS(cfg.AllowedOrigins))
	r.Use(middleware.RequestSizeLimit(cfg.MaxRequestSize))
	r.Use(middleware.WAF(log)) // basic WAF rules
	r.Use(middleware.Prometheus())
	r.Use(middleware.RateLimit(rateLimiter, cfg.RateLimit))
	r.Use(middleware.Trace())

	// Health & metrics (no auth, no rate limit)
	r.GET("/health", health.Liveness)
	r.GET("/health/ready", health.Readiness(cfg))
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// Public endpoints (no auth, rate limited)
	public := r.Group("/api/v1")
	public.Use(middleware.RateLimitPublic(rateLimiter, cfg.RateLimit))
	{
		public.POST("/auth/login", proxy.Handle("auth-service", "/api/v1/auth/login"))
		public.POST("/auth/register", proxy.Handle("auth-service", "/api/v1/auth/register"))
		public.POST("/auth/refresh", proxy.Handle("auth-service", "/api/v1/auth/refresh"))
		public.POST("/auth/forgot-password", proxy.Handle("auth-service", "/api/v1/auth/forgot-password"))
		public.POST("/auth/reset-password", proxy.Handle("auth-service", "/api/v1/auth/reset-password"))
		public.GET("/products", proxy.Handle("catalog-service", "/api/v1/products"))
		public.GET("/products/:id", proxy.Handle("catalog-service", "/api/v1/products/:id"))
		public.GET("/categories", proxy.Handle("catalog-service", "/api/v1/categories"))
	}

	// Authenticated endpoints
	auth := r.Group("/api/v1")
	auth.Use(middleware.Authenticate(authVerifier, log))
	{
		// User profile
		auth.GET("/me", proxy.Handle("auth-service", "/api/v1/users/me"))
		auth.PUT("/me", proxy.Handle("auth-service", "/api/v1/users/me"))
		auth.POST("/auth/logout", proxy.Handle("auth-service", "/api/v1/auth/logout"))

		// Cart (buyer only)
		auth.GET("/cart", proxy.HandleWithRole("order-service", "/api/v1/cart", "buyer", "seller"))
		auth.POST("/cart", proxy.HandleWithRole("order-service", "/api/v1/cart", "buyer", "seller"))
		auth.DELETE("/cart/:id", proxy.HandleWithRole("order-service", "/api/v1/cart/:id", "buyer", "seller"))

		// Checkout (buyer only)
		auth.POST("/checkout", proxy.HandleWithRole("order-service", "/api/v1/checkout", "buyer"))

		// Orders
		auth.GET("/orders", proxy.Handle("order-service", "/api/v1/orders"))
		auth.GET("/orders/:id", proxy.Handle("order-service", "/api/v1/orders/:id"))
		auth.POST("/orders/:id/cancel", proxy.Handle("order-service", "/api/v1/orders/:id/cancel"))

		// Payments
		auth.POST("/payments", proxy.HandleWithRole("payment-service", "/api/v1/payments", "buyer"))
		auth.GET("/payments/:id", proxy.Handle("payment-service", "/api/v1/payments/:id"))
		auth.POST("/payments/:id/refund", proxy.HandleWithRole("payment-service", "/api/v1/payments/:id/refund", "admin", "superadmin"))

		// Withdrawals (seller)
		auth.POST("/withdrawals", proxy.HandleWithRole("payment-service", "/api/v1/withdrawals", "seller", "admin"))
		auth.GET("/withdrawals", proxy.HandleWithRole("payment-service", "/api/v1/withdrawals", "seller", "admin"))

		// Seller: product management
		auth.POST("/products", proxy.HandleWithRole("catalog-service", "/api/v1/products", "seller", "admin"))
		auth.PUT("/products/:id", proxy.HandleWithRole("catalog-service", "/api/v1/products/:id", "seller", "admin"))
		auth.DELETE("/products/:id", proxy.HandleWithRole("catalog-service", "/api/v1/products/:id", "seller", "admin"))
		auth.PATCH("/products/:id/stock", proxy.HandleWithRole("catalog-service", "/api/v1/products/:id/stock", "seller", "admin"))

		// Admin
		auth.GET("/admin/users", proxy.HandleWithRole("auth-service", "/api/v1/admin/users", "admin", "superadmin"))
		auth.PATCH("/admin/users/:id/role", proxy.HandleWithRole("auth-service", "/api/v1/admin/users/:id/role", "superadmin"))
		auth.PATCH("/admin/users/:id/ban", proxy.HandleWithRole("auth-service", "/api/v1/admin/users/:id/ban", "admin", "superadmin"))
		auth.GET("/admin/audit", proxy.HandleWithRole("audit-service", "/api/v1/admin/audit", "superadmin"))
		auth.GET("/admin/errors", proxy.HandleWithRole("audit-service", "/api/v1/admin/errors", "admin", "superadmin"))
	}

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
		MaxHeaderBytes:    1 << 20, // 1MB
	}

	go func() {
		log.Info("API Gateway starting", "port", cfg.Port, "env", cfg.Environment)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal("server error", err)
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Info("shutting down API Gateway...")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Fatal("forced shutdown", err)
	}
	log.Info("API Gateway stopped")
}
