package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"ecommerce/shipping-service/internal/config"
	"ecommerce/shipping-service/internal/provider"
	"ecommerce/shipping-service/pkg/logger"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type ShippingService struct {
	db       *pgxpool.Pool
	redis    *redis.Client
	provider provider.ShippingProvider
	cfg      *config.Config
	log      *logger.Logger
}

func NewShippingService(db *pgxpool.Pool, rdb *redis.Client, prov provider.ShippingProvider, cfg *config.Config, log *logger.Logger) *ShippingService {
	return &ShippingService{db: db, redis: rdb, provider: prov, cfg: cfg, log: log}
}

type CalculateReq struct {
	Origin      string `json:"origin"`
	Destination string `json:"destination"`
	Weight      int    `json:"weight"`
	Couriers    []string `json:"couriers"`
}

type CalculateResp struct {
	Origin      string           `json:"origin"`
	Destination string           `json:"destination"`
	Weight      int              `json:"weight"`
	Rates       []provider.Rate  `json:"rates"`
	Cached      bool             `json:"cached"`
}

func (s *ShippingService) Calculate(ctx context.Context, req CalculateReq) (*CalculateResp, error) {
	if req.Weight <= 0 {
		return nil, errors.New("weight must be positive")
	}

	// Cache key
	cacheKey := fmt.Sprintf("rates:%s:%s:%d", req.Origin, req.Destination, req.Weight)
	cached, err := s.redis.Get(ctx, cacheKey).Result()
	if err == nil {
		var rates []provider.Rate
		if err := json.Unmarshal([]byte(cached), &rates); err == nil {
			return &CalculateResp{
				Origin: req.Origin, Destination: req.Destination,
				Weight: req.Weight, Rates: rates, Cached: true,
			}, nil
		}
	}

	// Call provider
	rates, err := s.provider.GetRates(ctx, req.Origin, req.Destination, req.Weight)
	if err != nil {
		return nil, fmt.Errorf("provider: %w", err)
	}

	// Filter by requested couriers
	if len(req.Couriers) > 0 {
		want := make(map[string]bool)
		for _, c := range req.Couriers {
			want[c] = true
		}
		filtered := rates[:0]
		for _, r := range rates {
			if want[r.Courier] {
				filtered = append(filtered, r)
			}
		}
		rates = filtered
	}

	// Cache for 24h
	if data, err := json.Marshal(rates); err == nil {
		_ = s.redis.Set(ctx, cacheKey, data, time.Duration(s.cfg.CourierCacheTTL)*time.Second).Err()
	}

	return &CalculateResp{
		Origin: req.Origin, Destination: req.Destination,
		Weight: req.Weight, Rates: rates, Cached: false,
	}, nil
}

func (s *ShippingService) Track(ctx context.Context, trackingNumber string) (*provider.TrackingInfo, error) {
	if trackingNumber == "" {
		return nil, errors.New("tracking number required")
	}
	return s.provider.Track(ctx, trackingNumber)
}

type CreateShipmentInternalReq struct {
	OrderID        string `json:"order_id"`
	Origin         string `json:"origin"`
	Destination    string `json:"destination"`
	Weight         int    `json:"weight"`
	Courier        string `json:"courier"`
	Service        string `json:"service"`
	RecipientName  string `json:"recipient_name"`
	RecipientPhone string `json:"recipient_phone"`
	RecipientAddr  string `json:"recipient_address"`
}

func (s *ShippingService) CreateShipment(ctx context.Context, req CreateShipmentInternalReq) (map[string]any, error) {
	if req.OrderID == "" {
		return nil, errors.New("order_id required")
	}

	// Create shipment via provider
	resp, err := s.provider.CreateShipment(ctx, provider.CreateShipmentReq{
		OrderID:        req.OrderID,
		Origin:         req.Origin,
		Destination:    req.Destination,
		Weight:         req.Weight,
		Courier:        req.Courier,
		Service:        req.Service,
		RecipientName:  req.RecipientName,
		RecipientPhone: req.RecipientPhone,
		RecipientAddr:  req.RecipientAddr,
	})
	if err != nil {
		return nil, err
	}

	// Save to DB
	shipmentID := uuid.New()
	_, err = s.db.Exec(ctx, `
		INSERT INTO shipping.shipments (id, order_id, tracking_number, courier, service, status, weight_grams, recipient_name, recipient_phone, recipient_address, origin, destination, provider)
		VALUES ($1, $2, $3, $4, $5, 'CREATED', $6, $7, $8, $9, $10, $11, $12)
	`, shipmentID, req.OrderID, resp.TrackingNumber, req.Courier, req.Service,
		req.Weight, req.RecipientName, req.RecipientPhone, req.RecipientAddr,
		req.Origin, req.Destination, resp.Provider)
	if err != nil {
		return nil, fmt.Errorf("insert shipment: %w", err)
	}

	s.log.Info("shipment created", "shipment_id", shipmentID, "tracking", resp.TrackingNumber)

	return map[string]any{
		"shipment_id":      shipmentID.String(),
		"tracking_number":  resp.TrackingNumber,
		"provider":         resp.Provider,
		"status":           "CREATED",
	}, nil
}

func (s *ShippingService) UpdateStatus(ctx context.Context, shipmentID, status, note string) error {
	cmd, err := s.db.Exec(ctx, `
		UPDATE shipping.shipments
		SET status = $1, updated_at = NOW()
		WHERE id = $2
	`, status, shipmentID)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return errors.New("shipment not found")
	}

	// Insert status history
	_, _ = s.db.Exec(ctx, `
		INSERT INTO shipping.shipment_events (id, shipment_id, status, note, occurred_at)
		VALUES ($1, $2, $3, $4, NOW())
	`, uuid.New(), shipmentID, status, note)

	return nil
}

func (s *ShippingService) GetUserShipments(ctx context.Context, userID string, page, size int) ([]map[string]any, int, error) {
	var total int
	err := s.db.QueryRow(ctx, `
		SELECT COUNT(*) FROM shipping.shipments s
		JOIN order_svc.orders o ON s.order_id::text = o.id::text
		WHERE o.user_id::text = $1
	`, userID).Scan(&total)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, 0, err
	}

	rows, err := s.db.Query(ctx, `
		SELECT s.id, s.order_id, s.tracking_number, s.courier, s.service, s.status,
		       s.weight_grams, s.created_at, s.updated_at
		FROM shipping.shipments s
		JOIN order_svc.orders o ON s.order_id::text = o.id::text
		WHERE o.user_id::text = $1
		ORDER BY s.created_at DESC
		LIMIT $2 OFFSET $3
	`, userID, size, page*size)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	shipments := []map[string]any{}
	for rows.Next() {
		var id, orderID, tracking, courier, service, status string
		var weight int
		var createdAt, updatedAt time.Time
		_ = rows.Scan(&id, &orderID, &tracking, &courier, &service, &status, &weight, &createdAt, &updatedAt)
		shipments = append(shipments, map[string]any{
			"id":              id,
			"order_id":        orderID,
			"tracking_number": tracking,
			"courier":         courier,
			"service":         service,
			"status":          status,
			"weight_grams":    weight,
			"created_at":      createdAt,
			"updated_at":      updatedAt,
		})
	}
	return shipments, total, nil
}

// Unused shim
var _ = http.StatusOK
