package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"ecommerce/order-service/internal/config"
	"ecommerce/order-service/internal/domain"
	"ecommerce/order-service/pkg/logger"

	"github.com/cenkalti/backoff/v4"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"github.com/shopspring/decimal"
	"github.com/segmentio/kafka-go"
)

// OrderService handles order & cart business logic with saga pattern
type OrderService struct {
	db       *pgxpool.Pool
	redis    *redis.Client
	kafka    *kafka.Writer
	cfg      *config.Config
	log      *logger.Logger
}

func NewOrderService(db *pgxpool.Pool, redis *redis.Client, kafka *kafka.Writer, cfg *config.Config, log *logger.Logger) *OrderService {
	return &OrderService{db: db, redis: redis, kafka: kafka, cfg: cfg, log: log}
}

// ===== Cart =====

func (s *OrderService) GetOrCreateCart(ctx context.Context, userID uuid.UUID) (*domain.Cart, error) {
	// Try get existing
	cart, err := s.getCartByUserID(ctx, userID)
	if err != nil {
		return nil, err
	}
	if cart != nil {
		// Refresh expiration
		_, err = s.db.Exec(ctx,
			`UPDATE order_svc.carts SET expires_at = NOW() + INTERVAL '168 hours' WHERE id = $1`,
			cart.ID)
		if err != nil {
			s.log.Error("failed to refresh cart expiry", err, "cart_id", cart.ID)
		}
		return cart, nil
	}

	// Create new
	cartID := uuid.New()
	_, err = s.db.Exec(ctx,
		`INSERT INTO order_svc.carts (id, user_id, expires_at) VALUES ($1, $2, NOW() + INTERVAL '168 hours')`,
		cartID, userID)
	if err != nil {
		return nil, fmt.Errorf("create cart: %w", err)
	}
	return &domain.Cart{
		ID:        cartID,
		UserID:    userID,
		Items:     []domain.CartItem{},
		ExpiresAt: time.Now().Add(168 * time.Hour),
	}, nil
}

func (s *OrderService) getCartByUserID(ctx context.Context, userID uuid.UUID) (*domain.Cart, error) {
	cart := &domain.Cart{Items: []domain.CartItem{}}
	err := s.db.QueryRow(ctx,
		`SELECT id, user_id, expires_at, created_at, updated_at
		 FROM order_svc.carts WHERE user_id = $1`, userID).Scan(
		&cart.ID, &cart.UserID, &cart.ExpiresAt, &cart.CreatedAt, &cart.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	// Load items
	rows, err := s.db.Query(ctx,
		`SELECT id, cart_id, product_id, quantity, unit_price, product_name, seller_id,
		        reserved, reservation_id, created_at, updated_at
		 FROM order_svc.cart_items WHERE cart_id = $1 ORDER BY created_at`, cart.ID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var item domain.CartItem
		err := rows.Scan(&item.ID, &item.CartID, &item.ProductID, &item.Quantity,
			&item.UnitPrice, &item.ProductName, &item.SellerID,
			&item.Reserved, &item.ReservationID, &item.CreatedAt, &item.UpdatedAt)
		if err != nil {
			return nil, err
		}
		cart.Items = append(cart.Items, item)
	}
	return cart, nil
}

func (s *OrderService) AddToCart(ctx context.Context, userID uuid.UUID, productID uuid.UUID, quantity int) (*domain.Cart, error) {
	if quantity <= 0 || quantity > s.cfg.Cart.MaxQtyPerItem {
		return nil, errors.New("invalid quantity")
	}

	// Fetch product info from catalog-service (with retry)
	product, err := s.fetchProduct(ctx, productID)
	if err != nil {
		return nil, fmt.Errorf("fetch product: %w", err)
	}
	if !product.IsActive || product.Status != "ACTIVE" {
		return nil, errors.New("product not available")
	}
	if product.AvailableStock < quantity {
		return nil, fmt.Errorf("insufficient stock: available %d, requested %d", product.AvailableStock, quantity)
	}

	// Get or create cart
	cart, err := s.GetOrCreateCart(ctx, userID)
	if err != nil {
		return nil, err
	}

	// Check item count limit
	if len(cart.Items) >= s.cfg.Cart.MaxItems {
		return nil, fmt.Errorf("cart limit reached (%d items)", s.cfg.Cart.MaxItems)
	}

	// Upsert cart item
	_, err = s.db.Exec(ctx, `
		INSERT INTO order_svc.cart_items (id, cart_id, product_id, quantity, unit_price, product_name, seller_id, reserved)
		VALUES ($1, $2, $3, $4, $5, $6, $7, false)
		ON CONFLICT (cart_id, product_id)
		DO UPDATE SET quantity = order_svc.cart_items.quantity + EXCLUDED.quantity,
		              unit_price = EXCLUDED.unit_price,
		              product_name = EXCLUDED.product_name,
		              updated_at = NOW()
	`, uuid.New(), cart.ID, productID, quantity, product.Price, product.Name, product.SellerID)
	if err != nil {
		return nil, fmt.Errorf("add to cart: %w", err)
	}

	return s.getCartByUserID(ctx, userID)
}

func (s *OrderService) UpdateCartItem(ctx context.Context, userID, itemID uuid.UUID, quantity int) (*domain.Cart, error) {
	if quantity <= 0 || quantity > s.cfg.Cart.MaxQtyPerItem {
		return nil, errors.New("invalid quantity")
	}
	cart, err := s.getCartByUserID(ctx, userID)
	if err != nil {
		return nil, err
	}
	if cart == nil {
		return nil, errors.New("cart not found")
	}
	// Verify item belongs to user's cart
	cmd, err := s.db.Exec(ctx,
		`UPDATE order_svc.cart_items SET quantity = $1, updated_at = NOW()
		 WHERE id = $2 AND cart_id = $3`, quantity, itemID, cart.ID)
	if err != nil {
		return nil, err
	}
	if cmd.RowsAffected() == 0 {
		return nil, errors.New("cart item not found")
	}
	return s.getCartByUserID(ctx, userID)
}

func (s *OrderService) RemoveFromCart(ctx context.Context, userID, itemID uuid.UUID) error {
	cart, err := s.getCartByUserID(ctx, userID)
	if err != nil {
		return err
	}
	if cart == nil {
		return errors.New("cart not found")
	}
	_, err = s.db.Exec(ctx,
		`DELETE FROM order_svc.cart_items WHERE id = $1 AND cart_id = $2`, itemID, cart.ID)
	return err
}

func (s *OrderService) ClearCart(ctx context.Context, userID uuid.UUID) error {
	cart, err := s.getCartByUserID(ctx, userID)
	if err != nil {
		return err
	}
	if cart == nil {
		return nil
	}
	_, err = s.db.Exec(ctx, `DELETE FROM order_svc.cart_items WHERE cart_id = $1`, cart.ID)
	return err
}

// ===== Checkout (Saga) =====

type CheckoutRequest struct {
	ShippingAddress string `json:"shipping_address"`
	PaymentMethod   string `json:"payment_method"`
	IdempotencyKey  string `json:"-"`
}

// Checkout performs saga:
// 1. Validate cart & stock
// 2. Reserve stock di catalog-service
// 3. Create order (PENDING)
// 4. Return order (frontend will call payment-service)
func (s *OrderService) Checkout(ctx context.Context, userID uuid.UUID, req CheckoutRequest) (*domain.Order, error) {
	cart, err := s.getCartByUserID(ctx, userID)
	if err != nil {
		return nil, err
	}
	if cart == nil || len(cart.Items) == 0 {
		return nil, errors.New("cart is empty")
	}
	if len(cart.Items) > s.cfg.Order.MaxItemsPerOrder {
		return nil, fmt.Errorf("too many items in order (max %d)", s.cfg.Order.MaxItemsPerOrder)
	}
	if req.ShippingAddress == "" {
		return nil, errors.New("shipping address required")
	}
	if req.PaymentMethod == "" {
		return nil, errors.New("payment method required")
	}

	// Calculate totals
	total := decimal.NewFromInt(0)
	items := make([]domain.OrderItem, 0, len(cart.Items))
	for _, ci := range cart.Items {
		subtotal := ci.UnitPrice.Mul(decimal.NewFromInt(int64(ci.Quantity)))
		total = total.Add(subtotal)
		items = append(items, domain.OrderItem{
			ID:          uuid.New(),
			ProductID:   ci.ProductID,
			ProductName: ci.ProductName,
			Quantity:    ci.Quantity,
			UnitPrice:   ci.UnitPrice,
			Subtotal:    subtotal,
			SellerID:    ci.SellerID,
		})
	}

	orderID := uuid.New()
	expiresAt := time.Now().Add(15 * time.Minute) // 15 min to pay

	// Start transaction
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// Create order
	_, err = tx.Exec(ctx, `
		INSERT INTO order_svc.orders
			(id, user_id, status, total_amount, currency, shipping_address,
			 shipping_cost, tax_amount, payment_method, expires_at, version)
		VALUES ($1, $2, 'PENDING', $3, 'IDR', $4, 0, 0, $5, $6, 1)
	`, orderID, userID, total, req.ShippingAddress, req.PaymentMethod, expiresAt)
	if err != nil {
		return nil, fmt.Errorf("create order: %w", err)
	}

	// Create order items
	for _, item := range items {
		_, err = tx.Exec(ctx, `
			INSERT INTO order_svc.order_items
				(id, order_id, product_id, product_name, product_sku, quantity, unit_price, subtotal, seller_id)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		`, item.ID, orderID, item.ProductID, item.ProductName, "", item.Quantity,
			item.UnitPrice, item.Subtotal, item.SellerID)
		if err != nil {
			return nil, fmt.Errorf("create order item: %w", err)
		}
	}

	// Reserve stock in catalog-service (HTTP call)
	compensations := []func(){}
	for _, item := range items {
		item := item
		reservationID, err := s.reserveStockWithRetry(ctx, item.ProductID, item.Quantity, userID, cart.ID)
		if err != nil {
			// Run compensations in reverse order
			for i := len(compensations) - 1; i >= 0; i-- {
				compensations[i]()
			}
			return nil, fmt.Errorf("reserve stock for product %s: %w", item.ProductID, err)
		}
		compensations = append(compensations, func() {
			_ = s.releaseStock(ctx, *reservationID)
		})
		// Update order item with reservation ID
		_, err = tx.Exec(ctx,
			`UPDATE order_svc.order_items SET reservation_id = $1 WHERE id = $2`,
			reservationID, item.ID)
		if err != nil {
			return nil, fmt.Errorf("update reservation id: %w", err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		// Compensate reservations
		for i := len(compensations) - 1; i >= 0; i-- {
			compensations[i]()
		}
		return nil, fmt.Errorf("commit: %w", err)
	}

	// Clear cart
	_, _ = s.db.Exec(ctx, `DELETE FROM order_svc.cart_items WHERE cart_id = $1`, cart.ID)

	// Publish event
	s.publishOrderEvent(ctx, "order.created", orderID, userID, map[string]any{
		"total":     total.String(),
		"items":     len(items),
		"expires_at": expiresAt,
	})

	s.log.Info("order created", "order_id", orderID, "user_id", userID, "total", total.String())
	return s.GetOrder(ctx, orderID, userID)
}

func (s *OrderService) GetOrder(ctx context.Context, orderID, userID uuid.UUID) (*domain.Order, error) {
	order := &domain.Order{Items: []domain.OrderItem{}}
	err := s.db.QueryRow(ctx, `
		SELECT id, user_id, status, total_amount, currency, shipping_address,
		       shipping_cost, tax_amount, payment_method, payment_id, expires_at,
		       confirmed_at, cancelled_at, cancel_reason, created_at, updated_at, version
		FROM order_svc.orders WHERE id = $1`, orderID).Scan(
		&order.ID, &order.UserID, &order.Status, &order.TotalAmount, &order.Currency,
		&order.ShippingAddress, &order.ShippingCost, &order.TaxAmount, &order.PaymentMethod,
		&order.PaymentID, &order.ExpiresAt, &order.ConfirmedAt, &order.CancelledAt,
		&order.CancelReason, &order.CreatedAt, &order.UpdatedAt, &order.Version,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, errors.New("order not found")
	}
	if err != nil {
		return nil, err
	}
	// Authorization check
	if order.UserID != userID {
		return nil, errors.New("forbidden")
	}
	// Load items
	rows, err := s.db.Query(ctx, `
		SELECT id, order_id, product_id, product_name, product_sku, quantity, unit_price, subtotal, reservation_id, seller_id, created_at
		FROM order_svc.order_items WHERE order_id = $1`, orderID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var item domain.OrderItem
		err := rows.Scan(&item.ID, &item.OrderID, &item.ProductID, &item.ProductName,
			&item.ProductSKU, &item.Quantity, &item.UnitPrice, &item.Subtotal,
			&item.ReservationID, &item.SellerID, &item.CreatedAt)
		if err != nil {
			return nil, err
		}
		order.Items = append(order.Items, item)
	}
	return order, nil
}

func (s *OrderService) ListOrders(ctx context.Context, userID uuid.UUID, page, size int) ([]domain.Order, int, error) {
	if page < 0 {
		page = 0
	}
	if size <= 0 || size > 100 {
		size = 20
	}
	var total int
	err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM order_svc.orders WHERE user_id = $1`, userID).Scan(&total)
	if err != nil {
		return nil, 0, err
	}
	rows, err := s.db.Query(ctx, `
		SELECT id, user_id, status, total_amount, currency, shipping_address,
		       shipping_cost, tax_amount, payment_method, payment_id, expires_at,
		       confirmed_at, cancelled_at, cancel_reason, created_at, updated_at, version
		FROM order_svc.orders WHERE user_id = $1
		ORDER BY created_at DESC
		LIMIT $2 OFFSET $3`, userID, size, page*size)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	orders := []domain.Order{}
	for rows.Next() {
		var o domain.Order
		err := rows.Scan(&o.ID, &o.UserID, &o.Status, &o.TotalAmount, &o.Currency,
			&o.ShippingAddress, &o.ShippingCost, &o.TaxAmount, &o.PaymentMethod,
			&o.PaymentID, &o.ExpiresAt, &o.ConfirmedAt, &o.CancelledAt,
			&o.CancelReason, &o.CreatedAt, &o.UpdatedAt, &o.Version)
		if err != nil {
			return nil, 0, err
		}
		orders = append(orders, o)
	}
	return orders, total, nil
}

func (s *OrderService) CancelOrder(ctx context.Context, orderID, userID uuid.UUID, reason string) (*domain.Order, error) {
	order, err := s.GetOrder(ctx, orderID, userID)
	if err != nil {
		return nil, err
	}
	if !order.Status.CanTransitionTo(domain.OrderStatusCancelled) {
		return nil, fmt.Errorf("cannot cancel order in status %s", order.Status)
	}

	// Update order status
	cmd, err := s.db.Exec(ctx, `
		UPDATE order_svc.orders
		SET status = 'CANCELLED', cancelled_at = NOW(), cancel_reason = $1, version = version + 1
		WHERE id = $2 AND version = $3`,
		reason, orderID, order.Version)
	if err != nil {
		return nil, err
	}
	if cmd.RowsAffected() == 0 {
		return nil, errors.New("concurrent update, please retry")
	}

	// Release stock reservations
	for _, item := range order.Items {
		if item.ReservationID != nil {
			_ = s.releaseStock(ctx, *item.ReservationID)
		}
	}

	// Publish event
	s.publishOrderEvent(ctx, "order.cancelled", orderID, userID, map[string]any{
		"reason": reason,
	})

	return s.GetOrder(ctx, orderID, userID)
}

// UpdatePaymentStatus called by payment-service after payment processed
func (s *OrderService) UpdatePaymentStatus(ctx context.Context, orderID uuid.UUID, paymentID uuid.UUID, status string) error {
	order := &domain.Order{}
	err := s.db.QueryRow(ctx, `
		SELECT id, user_id, status, version FROM order_svc.orders WHERE id = $1`, orderID).
		Scan(&order.ID, &order.UserID, &order.Status, &order.Version)
	if err != nil {
		return fmt.Errorf("order not found: %w", err)
	}

	switch status {
	case "SUCCEEDED":
		if !order.Status.CanTransitionTo(domain.OrderStatusPaid) {
			return fmt.Errorf("invalid transition: %s -> PAID", order.Status)
		}
		_, err = s.db.Exec(ctx, `
			UPDATE order_svc.orders
			SET status = 'PAID', payment_id = $1, confirmed_at = NOW(), version = version + 1
			WHERE id = $2 AND version = $3`, paymentID, orderID, order.Version)
		if err != nil {
			return err
		}
		// Confirm stock reservations
		items, _ := s.db.Query(ctx, `SELECT reservation_id FROM order_svc.order_items WHERE order_id = $1`, orderID)
		defer items.Close()
		for items.Next() {
			var resID *uuid.UUID
			_ = items.Scan(&resID)
			if resID != nil {
				_ = s.confirmStock(ctx, *resID)
			}
		}
		s.publishOrderEvent(ctx, "order.paid", orderID, order.UserID, map[string]any{
			"payment_id": paymentID,
		})

	case "FAILED":
		// Keep order PENDING so user can retry payment (still within expiry window)
		// If expired, a separate cron will cancel it
		s.publishOrderEvent(ctx, "order.payment_failed", orderID, order.UserID, map[string]any{
			"payment_id": paymentID,
		})
	}
	return nil
}

// ===== Helpers =====

type productInfo struct {
	ID             uuid.UUID `json:"id"`
	Name           string    `json:"name"`
	Price          decimal.Decimal `json:"price"`
	SellerID       uuid.UUID `json:"seller_id"`
	AvailableStock int       `json:"available_stock"`
	IsActive       bool      `json:"is_active"`
	Status         string    `json:"status"`
}

func (s *OrderService) fetchProduct(ctx context.Context, productID uuid.UUID) (*productInfo, error) {
	url := fmt.Sprintf("%s/api/v1/products/%s", s.cfg.CatalogSvcURL, productID)

	var result *productInfo
	bo := backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 3)
	err := backoff.Retry(func() error {
		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		// Propagate tracing
		req.Header.Set("X-Correlation-Id", ctx.Value("correlation_id").(string))
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		if resp.StatusCode != 200 {
			return fmt.Errorf("catalog returned %d", resp.StatusCode)
		}
		var p productInfo
		if err := json.NewDecoder(resp.Body).Decode(&p); err != nil {
			return err
		}
		result = &p
		return nil
	}, bo)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (s *OrderService) reserveStockWithRetry(ctx context.Context, productID uuid.UUID, qty int, userID, cartID uuid.UUID) (*uuid.UUID, error) {
	body := fmt.Sprintf(`{"product_id":"%s","quantity":%d,"user_id":"%s","cart_id":"%s"}`,
		productID, qty, userID, cartID)
	url := fmt.Sprintf("%s/api/v1/internal/products/%s/reserve", s.cfg.CatalogSvcURL, productID)

	var reservationID *uuid.UUID
	bo := backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 3)
	err := backoff.Retry(func() error {
		req, _ := http.NewRequestWithContext(ctx, "POST", url, []byte(body))
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusConflict {
			return backoff.Permanent(fmt.Errorf("insufficient stock"))
		}
		if resp.StatusCode != 200 {
			return fmt.Errorf("catalog returned %d", resp.StatusCode)
		}
		var result struct {
			ReservationID uuid.UUID `json:"reservation_id"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
			return err
		}
		reservationID = &result.ReservationID
		return nil
	}, bo)
	return reservationID, err
}

func (s *OrderService) releaseStock(ctx context.Context, reservationID uuid.UUID) error {
	url := fmt.Sprintf("%s/api/v1/internal/reservations/%s/release", s.cfg.CatalogSvcURL, reservationID)
	req, _ := http.NewRequestWithContext(ctx, "POST", url, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		s.log.Error("failed to release stock", err, "reservation_id", reservationID)
		return err
	}
	resp.Body.Close()
	return nil
}

func (s *OrderService) confirmStock(ctx context.Context, reservationID uuid.UUID) error {
	url := fmt.Sprintf("%s/api/v1/internal/reservations/%s/confirm", s.cfg.CatalogSvcURL, reservationID)
	req, _ := http.NewRequestWithContext(ctx, "POST", url, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		s.log.Error("failed to confirm stock", err, "reservation_id", reservationID)
		return err
	}
	resp.Body.Close()
	return nil
}

func (s *OrderService) publishOrderEvent(ctx context.Context, action string, orderID, userID uuid.UUID, extra map[string]any) {
	event := map[string]any{
		"event_id":    uuid.New().String(),
		"occurred_at": time.Now().UTC().Format(time.RFC3339Nano),
		"producer":    "order-service",
		"action":      action,
		"actor":       map[string]any{"user_id": userID.String()},
		"resource": map[string]any{
			"type": "order",
			"id":   orderID.String(),
		},
		"version": "1.0",
	}
	for k, v := range extra {
		event[k] = v
	}
	msg, _ := json.Marshal(event)
	if err := s.kafka.WriteMessages(ctx, kafka.Message{
		Key:   orderID.String(),
		Value: msg,
		Topic: "ecommerce.order.events",
	}); err != nil {
		s.log.Error("failed to publish order event", err, "action", action)
	}
}
