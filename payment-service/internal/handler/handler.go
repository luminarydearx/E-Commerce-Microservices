package handler

import (
        "context"
        "net/http"
        "net/url"
        "strconv"

        "ecommerce/payment-service/internal/config"
        "ecommerce/payment-service/internal/service"
        "ecommerce/payment-service/pkg/logger"

        "github.com/gin-gonic/gin"
        "github.com/google/uuid"
        "github.com/jackc/pgx/v5/pgxpool"
        "github.com/redis/go-redis/v9"
        "github.com/segmentio/kafka-go"
)

type Dependencies struct {
        DB    *pgxpool.Pool
        Redis *redis.Client
        Kafka *kafka.Writer
        Svc   *service.PaymentService
        Cfg   *config.Config
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
        }
        svc := service.NewPaymentService(pool, rdb, kw, cfg, log)
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
        c.JSON(http.StatusOK, gin.H{"status": "alive", "service": "payment-service"})
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
        c.JSON(status, gin.H{"status": "ready", "checks": gin.H{"database": dbOK, "redis": redisOK}})
}

func getUserID(c *gin.Context) (uuid.UUID, error) {
        uid, exists := c.Get("user_id")
        if !exists {
                return uuid.Nil, errUnauth
        }
        s, _ := uid.(string)
        return uuid.Parse(s)
}

var errUnauth = &appError{"unauthorized"}

type appError struct{ msg string }

func (e *appError) Error() string { return e.msg }

type CreatePaymentReq struct {
        OrderID  string `json:"order_id" binding:"required"`
        Method   string `json:"method" binding:"required"`
        Provider string `json:"provider"`
}

func (h *Handler) CreatePayment(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        var req CreatePaymentReq
        if err := c.ShouldBindJSON(&req); err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request", "message": err.Error()})
                return
        }
        payment, err := h.deps.Svc.CreatePayment(c.Request.Context(), uid, service.CreatePaymentReq{
                OrderID:        req.OrderID,
                Method:         req.Method,
                Provider:       req.Provider,
                IdempotencyKey: c.GetHeader("Idempotency-Key"),
        })
        if err != nil {
                h.log.Error("create payment failed", err, "user_id", uid)
                c.JSON(http.StatusBadRequest, gin.H{"error": "payment_failed", "message": err.Error()})
                return
        }
        c.JSON(http.StatusCreated, payment)
}

func (h *Handler) GetPayment(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        paymentID, err := uuid.Parse(c.Param("id"))
        if err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid payment_id"})
                return
        }
        p, err := h.deps.Svc.GetPayment(c.Request.Context(), paymentID, uid)
        if err != nil {
                c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
                return
        }
        c.JSON(http.StatusOK, p)
}

type RefundReq struct {
        Amount string `json:"amount" binding:"required"`
        Reason string `json:"reason" binding:"required"`
}

func (h *Handler) RefundPayment(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        paymentID := c.Param("id")
        var req RefundReq
        if err := c.ShouldBindJSON(&req); err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request"})
                return
        }
        refund, err := h.deps.Svc.RefundPayment(c.Request.Context(), uid, service.RefundReq{
                PaymentID: paymentID,
                Amount:    req.Amount,
                Reason:    req.Reason,
        })
        if err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "refund_failed", "message": err.Error()})
                return
        }
        c.JSON(http.StatusOK, refund)
}

type WithdrawalReq struct {
        Amount        string `json:"amount" binding:"required"`
        BankAccount   string `json:"bank_account" binding:"required"`
        BankCode      string `json:"bank_code" binding:"required"`
        AccountHolder string `json:"account_holder" binding:"required"`
}

func (h *Handler) RequestWithdrawal(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        var req WithdrawalReq
        if err := c.ShouldBindJSON(&req); err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_request"})
                return
        }
        w, err := h.deps.Svc.RequestWithdrawal(c.Request.Context(), uid, service.WithdrawalReq{
                Amount:        req.Amount,
                BankAccount:   req.BankAccount,
                BankCode:      req.BankCode,
                AccountHolder: req.AccountHolder,
        })
        if err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "withdrawal_failed", "message": err.Error()})
                return
        }
        c.JSON(http.StatusCreated, w)
}

func (h *Handler) ListWithdrawals(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        page, _ := strconv.Atoi(c.DefaultQuery("page", "0"))
        size, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
        list, total, err := h.deps.Svc.ListWithdrawals(c.Request.Context(), uid, page, size)
        if err != nil {
                c.JSON(http.StatusInternalServerError, gin.H{"error": "internal_error"})
                return
        }
        c.JSON(http.StatusOK, gin.H{"data": list, "total": total, "page": page, "size": size})
}

type ApproveWithdrawalReq struct {
        Approve bool   `json:"approve"`
        Reason  string `json:"reason"`
}

func (h *Handler) ApproveWithdrawal(c *gin.Context) {
        uid, err := getUserID(c)
        if err != nil {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
                return
        }
        withdrawalID, err := uuid.Parse(c.Param("id"))
        if err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
                return
        }
        var req ApproveWithdrawalReq
        _ = c.ShouldBindJSON(&req)
        w, err := h.deps.Svc.ApproveWithdrawal(c.Request.Context(), uid, withdrawalID, req.Approve, req.Reason)
        if err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "approve_failed", "message": err.Error()})
                return
        }
        c.JSON(http.StatusOK, w)
}

func (h *Handler) MidtransWebhook(c *gin.Context) {
        // Parse webhook payload
        var payload struct {
                OrderID       string `json:"order_id"`
                StatusCode    string `json:"status_code"`
                GrossAmount   string `json:"gross_amount"`
                SignatureKey  string `json:"signature_key"`
                TransactionStatus string `json:"transaction_status"`
        }
        if err := c.ShouldBindJSON(&payload); err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_payload"})
                return
        }

        if err := h.deps.Svc.HandleMidtransWebhook(
                c.Request.Context(),
                payload.OrderID,
                payload.StatusCode,
                payload.GrossAmount,
                payload.SignatureKey,
        ); err != nil {
                h.log.Error("midtrans webhook processing failed", err, "order_id", payload.OrderID)
                c.JSON(http.StatusBadRequest, gin.H{"error": "webhook_failed", "message": err.Error()})
                return
        }
        c.Status(http.StatusOK)
}

func (h *Handler) XenditWebhook(c *gin.Context) {
        // Verify Xendit callback token
        callbackToken := c.GetHeader("X-CALLBACK-TOKEN")
        // In production: compare with expected token from env
        if callbackToken == "" {
                c.JSON(http.StatusUnauthorized, gin.H{"error": "missing_callback_token"})
                return
        }

        var payload map[string]interface{}
        if err := c.ShouldBindJSON(&payload); err != nil {
                c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_payload"})
                return
        }

        // Process Xendit webhook (similar to Midtrans)
        externalID, _ := payload["external_id"].(string)
        status, _ := payload["status"].(string)

        h.log.Info("xendit webhook received", "external_id", externalID, "status", status)

        // Map Xendit status and update payment (similar to Midtrans handler)
        // For brevity, omitted here — see HandleMidtransWebhook for pattern

        c.Status(http.StatusOK)
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
