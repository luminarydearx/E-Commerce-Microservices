package main

import (
        "context"
        "net/http"
        "os"
        "os/signal"
        "syscall"
        "time"

        "ecommerce/order-service/internal/config"
        "ecommerce/order-service/internal/handler"
        "ecommerce/order-service/internal/middleware"
        "ecommerce/order-service/pkg/logger"
        "ecommerce/order-service/pkg/tracing"

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

        shutdownTracer, err := tracing.InitTracer("order-service", cfg.OtelEndpoint)
        if err != nil {
                log.Fatal("failed to init tracer", err)
        }
        defer func() {
                ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
                defer cancel()
                _ = shutdownTracer(ctx)
        }()

        deps, err := handler.NewDependencies(cfg, log)
        if err != nil {
                log.Fatal("failed to init dependencies", err)
        }
        defer deps.Close()

        if cfg.Environment == "production" {
                gin.SetMode(gin.ReleaseMode)
        }
        r := gin.New()
        r.Use(middleware.RequestID())
        r.Use(middleware.CorrelationID())
        r.Use(middleware.Logger(log))
        r.Use(middleware.Recovery(log))
        r.Use(middleware.SecurityHeaders())
        r.Use(middleware.CORS(cfg.AllowedOrigins))
        r.Use(middleware.IdempotencyRequired(log, deps.Redis))
        r.Use(otelgin.Middleware("order-service"))

        h := handler.NewHandler(deps, log)

        r.GET("/health", h.Health)
        r.GET("/health/ready", h.Readiness)
        r.GET("/metrics", gin.WrapH(promhttp.Handler()))

        api := r.Group("/api/v1")
        api.Use(middleware.Authenticate(log))
        {
                api.GET("/cart", h.GetCart)
                api.POST("/cart", h.AddToCart)
                api.PUT("/cart/:item_id", h.UpdateCartItem)
                api.DELETE("/cart/:item_id", h.RemoveFromCart)
                api.DELETE("/cart", h.ClearCart)

                api.POST("/checkout", h.Checkout)
                api.GET("/orders", h.ListOrders)
                api.GET("/orders/:id", h.GetOrder)
                api.POST("/orders/:id/cancel", h.CancelOrder)
                api.POST("/orders/:id/complete", h.CompleteOrder) // internal: called by payment-service

                // Internal endpoints (mTLS protected)
                internal := r.Group("/internal")
                internal.Use(middleware.InternalOnly(cfg.InternalToken))
                {
                        internal.POST("/orders/:id/payment-status", h.UpdatePaymentStatus)
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
                log.Info("order-service starting", "port", cfg.Port)
                if err := srv.ListenAndServe(); err != nil {
                        log.Fatal("server error", err)
                }
        }()

        quit := make(chan os.Signal, 1)
        signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
        <-quit
        log.Info("shutting down order-service...")

        ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
        defer cancel()
        _ = srv.Shutdown(ctx)
        log.Info("order-service stopped")
}
