package handler

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	"ecommerce/order-service/internal/config"
	"ecommerce/order-service/internal/domain"
	"ecommerce/order-service/internal/service"
	"ecommerce/order-service/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"github.com/segmentio/kafka-go"
)

type Dependencies struct {
	DB     *pgxpool.Pool
	Redis  *redis.Client
	Kafka  *kafka.Writer
	Svc    *service.OrderService
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
	kw := &kafka.Writer{
		Addr:         kafka.TCP(cfg.KafkaBrokers...),
		Balancer:     &kafka.LeastBytes{},
		RequiredAcks: kafka.RequireAll,
		Async:        false,
	}
	svc := service.NewOrderService(pool, rdb, kw, cfg, log)
	return &Dependencies{DB: pool, Redis: rdb, Kafka: kw, Svc: svc, Cfg: cfg}, nil
}

func (d *Dependencies) Close() {
	d.DB.Close()
	d.Redis.Close()
	_ = d.Kafka.Close()
}

type Handler struct {
	deps *Dependencies
	log  *logger.Logger
}

func NewHandler(deps *Dependencies, log *logger.Logger) *Handler {
	return &Handler{deps: deps, log: log}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "alive", "service": "order-service"})
}

func (h *Handler) Readiness(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2_000_000_000)
	defer cancel()
	dbOK := h.deps.DB.Ping(ctx) == nil
	redisOK := h.deps.Redis.Ping(ctx).Err() == nil
	status := http.StatusOK
	if !dbOK || !redisOK {
		status = http.StatusServiceUnavailable
	}
	c.JSON(status, gin.H{
		"status":  "ready",
		"checks":  gin.H{"database": dbOK, "redis": redisOK},
	})
}

func getUserID(c *gin.Context) (uuid.UUID, error) {
	uid, exists := c.Get("user_id")
	if !exists {
		return uuid.Nil, errors.New("not authenticated")
	}
	s, ok := uid.(string)
	if !ok {
		return uuid.Nil, errors.New("invalid user_id type")
	}
	return uuid.Parse(s)
}

func (h *Handler) GetCart(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	cart, err := h.deps.Svc.GetOrCreateCart(c.Request.Context(), uid)
	if err != nil {
		h.log.Error("get cart failed", err, "user_id", uid)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal_error"})
		return
	}
	c.JSON(http.StatusOK, cart)
}

type AddToCartReq struct {
	ProductID string `json:"product_id" binding:"required"`
	Quantity  int    `json:"quantity" binding:"required,min=1"`
}

func (h *Handler) AddToCart(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	var req AddToCartReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	pid, err := uuid.Parse(req.ProductID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid product_id"})
		return
	}
	cart, err := h.deps.Svc.AddToCart(c.Request.Context(), uid, pid, req.Quantity)
	if err != nil {
		h.log.Warn("add to cart failed", "error", err.Error(), "user_id", uid)
		c.JSON(http.StatusBadRequest, gin.H{"error": "add_to_cart_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, cart)
}

type UpdateCartReq struct {
	Quantity int `json:"quantity" binding:"required,min=1"`
}

func (h *Handler) UpdateCartItem(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	itemID, err := uuid.Parse(c.Param("item_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid item_id"})
		return
	}
	var req UpdateCartReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request"})
		return
	}
	cart, err := h.deps.Svc.UpdateCartItem(c.Request.Context(), uid, itemID, req.Quantity)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "update_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, cart)
}

func (h *Handler) RemoveFromCart(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	itemID, err := uuid.Parse(c.Param("item_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid item_id"})
		return
	}
	if err := h.deps.Svc.RemoveFromCart(c.Request.Context(), uid, itemID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "remove_failed", "message": err.Error()})
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *Handler) ClearCart(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	if err := h.deps.Svc.ClearCart(c.Request.Context(), uid); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "clear_failed"})
		return
	}
	c.Status(http.StatusNoContent)
}

type CheckoutReq struct {
	ShippingAddress string `json:"shipping_address" binding:"required"`
	PaymentMethod   string `json:"payment_method" binding:"required"`
}

func (h *Handler) Checkout(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	var req CheckoutReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
		return
	}
	order, err := h.deps.Svc.Checkout(c.Request.Context(), uid, service.CheckoutRequest{
		ShippingAddress: req.ShippingAddress,
		PaymentMethod:   req.PaymentMethod,
	})
	if err != nil {
		h.log.Error("checkout failed", err, "user_id", uid)
		c.JSON(http.StatusBadRequest, gin.H{"error": "checkout_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, order)
}

func (h *Handler) ListOrders(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	page, _ := strconv.Atoi(c.DefaultQuery("page", "0"))
	size, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	orders, total, err := h.deps.Svc.ListOrders(c.Request.Context(), uid, page, size)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal_error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": orders, "total": total, "page": page, "size": size})
}

func (h *Handler) GetOrder(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	orderID, err := uuid.Parse(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid order_id"})
		return
	}
	order, err := h.deps.Svc.GetOrder(c.Request.Context(), orderID, uid)
	if err != nil {
		if err.Error() == "order not found" {
			c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
			return
		}
		if err.Error() == "forbidden" {
			c.JSON(http.StatusForbidden, gin.H{"error": "forbidden"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "internal_error"})
		return
	}
	c.JSON(http.StatusOK, order)
}

type CancelReq struct {
	Reason string `json:"reason"`
}

func (h *Handler) CancelOrder(c *gin.Context) {
	uid, err := getUserID(c)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}
	orderID, err := uuid.Parse(c.Param("id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid order_id"})
		return
	}
	var req CancelReq
	_ = c.ShouldBindJSON(&req)
	order, err := h.deps.Svc.CancelOrder(c.Request.Context(), orderID, uid, req.Reason)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "cancel_failed", "message": err.Error()})
		return
	}
	c.JSON(http.StatusOK, order)
}

type PaymentStatusReq struct {
	OrderID   string `json:"order_id" binding:"required"`
	PaymentID string `json:"payment_id" binding:"required"`
	Status    string `json:"status" binding:"required"`
}

func (h *Handler) UpdatePaymentStatus(c *gin.Context) {
	var req PaymentStatusReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request"})
		return
	}
	orderID, _ := uuid.Parse(req.OrderID)
	paymentID, _ := uuid.Parse(req.PaymentID)
	if err := h.deps.Svc.UpdatePaymentStatus(c.Request.Context(), orderID, paymentID, req.Status); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "update_failed", "message": err.Error()})
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *Handler) CompleteOrder(c *gin.Context) {
	// Stub: in real impl, called by fulfillment service when delivered
	c.Status(http.StatusNotImplemented)
}

// Suppress unused warning
var _ = domain.OrderStatusPending
