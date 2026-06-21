package handler

import (
	"context"
	"net/http"
	"net/url"
	"strconv"

	"ecommerce/shipping-service/internal/config"
	"ecommerce/shipping-service/internal/provider"
	"ecommerce/shipping-service/internal/service"
	"ecommerce/shipping-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type Dependencies struct {
	DB     *pgxpool.Pool
	Redis  *redis.Client
	Svc    *service.ShippingService
	Cfg    *config.Config
}

func NewDependencies(cfg *config.Config, log *logger.Logger) (*Dependencies, error) {
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, err
	}
	rdb := redis.NewClient(redisOptions(cfg.RedisURL))
	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, err
	}
	prov := provider.NewRajaOngkir(cfg.RajaOngkirKey, cfg.RajaOngkirURL)
	svc := service.NewShippingService(pool, rdb, prov, cfg, log)
	return &Dependencies{DB: pool, Redis: rdb, Svc: svc, Cfg: cfg}, nil
}

func (d *Dependencies) Close() {
	d.DB.Close()
	d.Redis.Close()
}

type Handler struct {
	deps *Dependencies
	log  *logger.Logger
}

func NewHandler(deps *Dependencies, log *logger.Logger) *Handler {
	return &Handler{deps: deps, log: log}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(200, gin.H{"status": "alive", "service": "shipping-service"})
}

func (h *Handler) CalculateShipping(c *gin.Context) {
	var req service.CalculateReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	resp, err := h.deps.Svc.Calculate(c.Request.Context(), req)
	if err != nil {
		c.JSON(400, gin.H{"error": "calculate_failed", "message": err.Error()})
		return
	}
	c.JSON(200, resp)
}

func (h *Handler) TrackShipment(c *gin.Context) {
	tkNumber := c.Param("tracking_number")
	if tkNumber == "" {
		c.JSON(400, gin.H{"error": "tracking_number required"})
		return
	}
	info, err := h.deps.Svc.Track(c.Request.Context(), tkNumber)
	if err != nil {
		c.JSON(400, gin.H{"error": "track_failed", "message": err.Error()})
		return
	}
	c.JSON(200, info)
}

func (h *Handler) GetUserShipments(c *gin.Context) {
	uid := c.GetString("user_id")
	page, _ := strconv.Atoi(c.DefaultQuery("page", "0"))
	size, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	shipments, total, err := h.deps.Svc.GetUserShipments(c.Request.Context(), uid, page, size)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	c.JSON(200, gin.H{"data": shipments, "total": total, "page": page, "size": size})
}

func (h *Handler) CreateShipment(c *gin.Context) {
	var req service.CreateShipmentInternalReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}
	result, err := h.deps.Svc.CreateShipment(c.Request.Context(), req)
	if err != nil {
		c.JSON(400, gin.H{"error": "create_failed", "message": err.Error()})
		return
	}
	c.JSON(201, result)
}

func (h *Handler) UpdateShipmentStatus(c *gin.Context) {
	shipmentID := c.Param("id")
	var req struct {
		Status string `json:"status"`
		Note   string `json:"note"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}
	if err := h.deps.Svc.UpdateStatus(c.Request.Context(), shipmentID, req.Status, req.Note); err != nil {
		c.JSON(400, gin.H{"error": "update_failed", "message": err.Error()})
		return
	}
	c.Status(204)
}

func (h *Handler) ListAllShipments(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"message": "admin list — implement with filters"})
}

func (h *Handler) GetShipment(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"message": "admin detail — implement"})
}

func redisOptions(redisURL string) *redis.Options {
	u, err := url.Parse(redisURL)
	if err != nil {
		return &redis.Options{Addr: "localhost:6379"}
	}
	opts := &redis.Options{Addr: u.Host}
	if u.User != nil {
		opts.Password, _ = u.User.Password()
	}
	return opts
}
