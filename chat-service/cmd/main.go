package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ecommerce/chat-service/internal/config"
	"ecommerce/chat-service/internal/handler"
	"ecommerce/chat-service/internal/hub"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}

	h := hub.NewHub()
	go h.Run()

	apiHandler := handler.NewHandler(h, cfg)

	if cfg.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(handler.RequestID())
	r.Use(handler.Logger())
	r.Use(handler.Recovery())
	r.Use(handler.SecurityHeaders())

	r.GET("/health", apiHandler.Health)
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// WebSocket endpoint — buyer/seller connect to chat
	r.GET("/ws/chat", apiHandler.Authenticate(), apiHandler.HandleWebSocket)

	// REST endpoints
	api := r.Group("/api/v1")
	api.Use(apiHandler.Authenticate())
	{
		api.GET("/chat/conversations", apiHandler.ListConversations)
		api.GET("/chat/conversations/:id/messages", apiHandler.GetMessages)
		api.POST("/chat/conversations", apiHandler.CreateConversation)
		api.PATCH("/chat/conversations/:id/read", apiHandler.MarkRead)
		api.DELETE("/chat/conversations/:id", apiHandler.DeleteConversation)
	}

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      0, // WebSocket: no timeout
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		log.Printf("chat-service starting on port %s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil {
			log.Fatalf("server error: %v", err)
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

// Suppress unused
var _ = json.Marshal
