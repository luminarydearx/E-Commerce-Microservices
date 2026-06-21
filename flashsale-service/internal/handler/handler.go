package handler

import (
	"context"
	"fmt"
	"strconv"
	"sync"
	"time"

	"ecommerce/flashsale-service/internal/config"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type Handler struct {
	pool *pgxpool.Pool
	rdb  *redis.Client
	cfg  *config.Config
	mu   sync.Mutex
}

func NewHandler(pool *pgxpool.Pool, rdb *redis.Client, cfg *config.Config) *Handler {
	return &Handler{pool: pool, rdb: rdb, cfg: cfg}
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(200, gin.H{"status": "alive", "service": "flashsale-service"})
}

func (h *Handler) Authenticate() gin.HandlerFunc {
	return func(c *gin.Context) {
		uid := c.GetHeader("X-User-Id")
		if uid == "" {
			c.AbortWithStatusJSON(401, gin.H{"error": "unauthorized"})
			return
		}
		c.Set("user_id", uid)
		roles := c.GetHeader("X-User-Roles")
		if roles != "" {
			c.Set("user_roles", roles)
		}
		c.Next()
	}
}

func (h *Handler) AdminOnly() gin.HandlerFunc {
	return func(c *gin.Context) {
		roles := c.GetString("user_roles")
		if !contains(roles, "admin") && !contains(roles, "superadmin") {
			c.AbortWithStatusJSON(403, gin.H{"error": "admin_required"})
			return
		}
		c.Next()
	}
}

func contains(s, sub string) bool {
	if s == "" || sub == "" {
		return false
	}
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

// ===== Public =====

func (h *Handler) ListActiveSales(c *gin.Context) {
	now := time.Now()
	rows, err := h.pool.Query(c.Request.Context(), `
		SELECT id, name, start_at, end_at, status
		FROM flashsale.sales
		WHERE status = 'ACTIVE' AND start_at <= $1 AND end_at >= $1
		ORDER BY end_at ASC
	`, now)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	defer rows.Close()

	sales := []map[string]any{}
	for rows.Next() {
		var id, name, status string
		var startAt, endAt time.Time
		_ = rows.Scan(&id, &name, &startAt, &endAt, &status)
		sales = append(sales, map[string]any{
			"id":       id,
			"name":     name,
			"start_at": startAt,
			"end_at":   endAt,
			"status":   status,
			"countdown_seconds": int(time.Until(endAt).Seconds()),
		})
	}
	c.JSON(200, gin.H{"data": sales})
}

func (h *Handler) GetFlashSale(c *gin.Context) {
	id := c.Param("id")
	var name, status string
	var startAt, endAt time.Time
	err := h.pool.QueryRow(c.Request.Context(), `
		SELECT name, start_at, end_at, status FROM flashsale.sales WHERE id = $1
	`, id).Scan(&name, &startAt, &endAt, &status)
	if err != nil {
		c.JSON(404, gin.H{"error": "not_found"})
		return
	}
	c.JSON(200, gin.H{
		"id":                 id,
		"name":               name,
		"start_at":           startAt,
		"end_at":             endAt,
		"status":             status,
		"countdown_seconds":  int(time.Until(endAt).Seconds()),
	})
}

func (h *Handler) ListFlashSaleItems(c *gin.Context) {
	id := c.Param("id")
	rows, err := h.pool.Query(c.Request.Context(), `
		SELECT id, product_id, original_price, sale_price, quota, sold, max_per_user
		FROM flashsale.items
		WHERE sale_id = $1
	`, id)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var itemID, productID string
		var origPrice, salePrice, quota, sold, maxPerUser int
		_ = rows.Scan(&itemID, &productID, &origPrice, &salePrice, &quota, &sold, &maxPerUser)
		items = append(items, map[string]any{
			"id":              itemID,
			"product_id":      productID,
			"original_price":  origPrice,
			"sale_price":      salePrice,
			"quota":           quota,
			"sold":            sold,
			"remaining":       quota - sold,
			"max_per_user":    maxPerUser,
			"discount_percent": int(float64(origPrice-salePrice) / float64(origPrice) * 100),
		})
	}
	c.JSON(200, gin.H{"data": items})
}

// ===== Queue System (anti-bot, anti-DDoS) =====

func (h *Handler) JoinQueue(c *gin.Context) {
	saleID := c.Param("id")
	uid := c.GetString("user_id")

	// Check queue size
	queueKey := "fs:queue:" + saleID
	queueLen, _ := h.rdb.LLen(c.Request.Context(), queueKey).Result()
	if int(queueLen) >= h.cfg.QueueMaxSize {
		c.JSON(429, gin.H{"error": "queue_full", "message": "please try again later"})
		return
	}

	// Check if user already in queue
	memberKey := "fs:queue:members:" + saleID
	exists, _ := h.rdb.SIsMember(c.Request.Context(), memberKey, uid).Result()
	if exists {
		// Get existing position
		pos, _ := h.rdb.LPos(c.Request.Context(), queueKey, uid, redis.LPosArgs{}).Result()
		c.JSON(200, gin.H{
			"status": "already_in_queue",
			"position": int(pos) + 1,
			"estimated_wait_seconds": (int(pos) + 1) * 5,
		})
		return
	}

	// Add to queue
	_ = h.rdb.RPush(c.Request.Context(), queueKey, uid).Err()
	_ = h.rdb.SAdd(c.Request.Context(), memberKey, uid).Err()
	_ = h.rdb.Expire(c.Request.Context(), queueKey, time.Duration(h.cfg.QueueSlotTTL)*time.Second)

	pos, _ := h.rdb.LPos(c.Request.Context(), queueKey, uid, redis.LPosArgs{}).Result()
	c.JSON(200, gin.H{
		"status": "queued",
		"position": int(pos) + 1,
		"estimated_wait_seconds": (int(pos) + 1) * 5,
	})
}

func (h *Handler) QueueStatus(c *gin.Context) {
	saleID := c.Param("id")
	uid := c.GetString("user_id")
	queueKey := "fs:queue:" + saleID

	pos, err := h.rdb.LPos(c.Request.Context(), queueKey, uid, redis.LPosArgs{}).Result()
	if err != nil {
		c.JSON(404, gin.H{"error": "not_in_queue"})
		return
	}

	// If first in queue, check if slot is available
	canBuy := false
	if pos == 0 {
		canBuy = true
	}
	c.JSON(200, gin.H{
		"position": int(pos) + 1,
		"can_buy":  canBuy,
		"estimated_wait_seconds": int(pos) * 5,
	})
}

func (h *Handler) AttemptBuy(c *gin.Context) {
	saleID := c.Param("id")
	itemID := c.Param("item_id")
	uid := c.GetString("user_id")

	// Verify user is at front of queue
	queueKey := "fs:queue:" + saleID
	pos, err := h.rdb.LPos(c.Request.Context(), queueKey, uid, redis.LPosArgs{}).Result()
	if err != nil || pos != 0 {
		c.JSON(403, gin.H{"error": "not_your_turn", "message": "wait for your queue turn"})
		return
	}

	// Atomically decrement stock with Lua script
	luaScript := `
	local stock_key = KEYS[1]
	local user_key = KEYS[2]
	local uid = ARGV[1]
	local max_per_user = tonumber(ARGV[2])

	-- Check user limit
	local bought = tonumber(redis.call('GET', user_key) or '0')
	if bought >= max_per_user then
		return -1  -- user limit reached
	end

	-- Check stock
	local stock = tonumber(redis.call('GET', stock_key) or '0')
	if stock <= 0 then
		return 0  -- out of stock
	end

	-- Decrement stock
	redis.call('DECR', stock_key)
	redis.call('INCR', user_key)
	return 1  -- success
	`
	stockKey := fmt.Sprintf("fs:stock:%s:%s", saleID, itemID)
	userKey := fmt.Sprintf("fs:user_bought:%s:%s:%s", saleID, itemID, uid)
	maxPerUser := 1 // configurable per item

	result, err := h.rdb.Eval(c.Request.Context(), luaScript, []string{stockKey, userKey}, uid, maxPerUser).Result()
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	res := result.(int64)
	if res == -1 {
		c.JSON(400, gin.H{"error": "user_limit_reached"})
		return
	}
	if res == 0 {
		c.JSON(400, gin.H{"error": "out_of_stock"})
		return
	}

	// Success — remove from queue
	_ = h.rdb.LPop(c.Request.Context(), queueKey).Err()

	// Generate purchase token (valid for 5 min to complete checkout)
	token := uuid.New().String()
	tokenKey := fmt.Sprintf("fs:purchase_token:%s", token)
	_ = h.rdb.Set(c.Request.Context(), tokenKey, fmt.Sprintf("%s:%s:%s", saleID, itemID, uid), 5*time.Minute).Err()

	// Update DB (sold count)
	_, _ = h.pool.Exec(c.Request.Context(), `
		UPDATE flashsale.items SET sold = sold + 1 WHERE id = $1 AND quota > sold
	`, itemID)

	c.JSON(200, gin.H{
		"status": "purchase_token_granted",
		"token":  token,
		"expires_in_seconds": 300,
		"message": "proceed to checkout with this token",
	})
}

// ===== Admin =====

func (h *Handler) CreateFlashSale(c *gin.Context) {
	var req struct {
		Name    string `json:"name"`
		StartAt string `json:"start_at"`
		EndAt   string `json:"end_at"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}

	id := uuid.New().String()
	startAt, _ := time.Parse(time.RFC3339, req.StartAt)
	endAt, _ := time.Parse(time.RFC3339, req.EndAt)

	status := "SCHEDULED"
	if time.Now().After(startAt) {
		status = "ACTIVE"
	}

	_, err := h.pool.Exec(c.Request.Context(), `
		INSERT INTO flashsale.sales (id, name, start_at, end_at, status)
		VALUES ($1, $2, $3, $4, $5)
	`, id, req.Name, startAt, endAt, status)
	if err != nil {
		c.JSON(500, gin.H{"error": "create_failed"})
		return
	}
	c.JSON(201, gin.H{"id": id, "name": req.Name, "status": status})
}

func (h *Handler) AddFlashSaleItem(c *gin.Context) {
	saleID := c.Param("id")
	var req struct {
		ProductID    string `json:"product_id"`
		OrigPrice    int    `json:"original_price"`
		SalePrice    int    `json:"sale_price"`
		Quota        int    `json:"quota"`
		MaxPerUser   int    `json:"max_per_user"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}

	itemID := uuid.New().String()
	_, err := h.pool.Exec(c.Request.Context(), `
		INSERT INTO flashsale.items (id, sale_id, product_id, original_price, sale_price, quota, sold, max_per_user)
		VALUES ($1, $2, $3, $4, $5, $6, 0, $7)
	`, itemID, saleID, req.ProductID, req.OrigPrice, req.SalePrice, req.Quota, req.MaxPerUser)
	if err != nil {
		c.JSON(500, gin.H{"error": "create_failed"})
		return
	}

	// Initialize Redis stock
	stockKey := fmt.Sprintf("fs:stock:%s:%s", saleID, itemID)
	_ = h.rdb.Set(c.Request.Context(), stockKey, req.Quota, 24*time.Hour).Err()

	c.JSON(201, gin.H{"id": itemID, "stock_initialized": true})
}

func (h *Handler) EndFlashSale(c *gin.Context) {
	saleID := c.Param("id")
	_, err := h.pool.Exec(c.Request.Context(), `
		UPDATE flashsale.sales SET status = 'ENDED', updated_at = NOW() WHERE id = $1
	`, saleID)
	if err != nil {
		c.JSON(500, gin.H{"error": "internal_error"})
		return
	}
	c.Status(204)
}

// Middleware
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-Id")
		if rid == "" {
			rid = uuid.New().String()
		}
		c.Set("request_id", rid)
		c.Writer.Header().Set("X-Request-Id", rid)
		c.Next()
	}
}

func Logger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		fmt.Printf("[%s] %s %s %d %dms\n",
			c.GetString("request_id"), c.Request.Method, c.Request.URL.Path,
			c.Writer.Status(), time.Since(start).Milliseconds())
	}
}

func Recovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			if r := recover(); r != nil {
				c.AbortWithStatusJSON(500, gin.H{"error": "internal_error"})
			}
		}()
		c.Next()
	}
}

func SecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Next()
	}
}

// Unused imports
var _ = context.Background
var _ = strconv.Atoi
