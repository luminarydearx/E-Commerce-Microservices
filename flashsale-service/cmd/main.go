package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ecommerce/flashsale-service/internal/config"
	"ecommerce/flashsale-service/internal/handler"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}

	pool, err := pgxpool.New(context.Background(), cfg.DatabaseURL)
	if err != nil {
		panic(err)
	}
	defer pool.Close()

	rdb := redis.NewClient(&redis.Options{Addr: cfg.RedisAddr})
	defer rdb.Close()

	h := handler.NewHandler(pool, rdb, cfg)

	if cfg.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(handler.RequestID())
	r.Use(handler.Logger())
	r.Use(handler.Recovery())
	r.Use(handler.SecurityHeaders())

	r.GET("/health", h.Health)
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// Public endpoints (rate limited strictly)
	r.GET("/api/v1/flash-sales/active", h.ListActiveSales)
	r.GET("/api/v1/flash-sales/:id", h.GetFlashSale)
	r.GET("/api/v1/flash-sales/:id/items", h.ListFlashSaleItems)

	// Buyer: join queue, attempt purchase (requires auth)
	auth := r.Group("/api/v1")
	auth.Use(h.Authenticate())
	{
		auth.POST("/flash-sales/:id/join-queue", h.JoinQueue)
		auth.GET("/flash-sales/:id/queue-status", h.QueueStatus)
		auth.POST("/flash-sales/:id/items/:item_id/buy", h.AttemptBuy)
	}

	// Admin: create flash sale
	admin := r.Group("/api/v1/admin")
	admin.Use(h.Authenticate())
	admin.Use(h.AdminOnly())
	{
		admin.POST("/flash-sales", h.CreateFlashSale)
		admin.POST("/flash-sales/:id/items", h.AddFlashSaleItem)
		admin.PATCH("/flash-sales/:id/end", h.EndFlashSale)
	}

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		log.Printf("flashsale-service starting on port %s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil {
			log.Fatalf("server: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}

var _ = json.Marshal
var _ = fmt.Sprintf
var _ = uuid.New
