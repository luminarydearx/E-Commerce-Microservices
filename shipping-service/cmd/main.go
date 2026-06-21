package main

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ecommerce/shipping-service/internal/config"
	"ecommerce/shipping-service/internal/handler"
	"ecommerce/shipping-service/pkg/logger"
	"ecommerce/shipping-service/pkg/tracing"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	otelgin "go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}

	log := logger.New(cfg.Environment)
	defer log.Sync()

	shutdown, err := tracing.InitTracer("shipping-service", cfg.OtelEndpoint)
	if err != nil {
		log.Fatal("tracer init", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(ctx)
	}()

	deps, err := handler.NewDependencies(cfg, log)
	if err != nil {
		log.Fatal("deps init", err)
	}
	defer deps.Close()

	if cfg.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(middleware.RequestID())
	r.Use(middleware.Logger(log))
	r.Use(middleware.Recovery(log))
	r.Use(middleware.SecurityHeaders())
	r.Use(otelgin.Middleware("shipping-service"))

	h := handler.NewHandler(deps, log)

	r.GET("/health", h.Health)
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	api := r.Group("/api/v1")
	api.Use(middleware.Authenticate())
	{
		// Calculate shipping cost
		api.POST("/shipping/calculate", h.CalculateShipping)

		// Track shipment
		api.GET("/shipping/track/:tracking_number", h.TrackShipment)

		// Get shipping history (user)
		api.GET("/shipping/history", h.GetUserShipments)

		// Internal: create shipment (called by order-service after payment confirmed)
		internal := r.Group("/internal")
		internal.Use(middleware.InternalOnly(cfg.InternalToken))
		{
			internal.POST("/shipments", h.CreateShipment)
			internal.PATCH("/shipments/:id/status", h.UpdateShipmentStatus)
		}

		// Admin
		admin := api.Group("/admin")
		admin.Use(middleware.AdminOnly())
		{
			admin.GET("/shipments", h.ListAllShipments)
			admin.GET("/shipments/:id", h.GetShipment)
		}
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
		log.Info("shipping-service starting", "port", cfg.Port)
		if err := srv.ListenAndServe(); err != nil {
			log.Fatal("server", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Info("shutting down...")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}
