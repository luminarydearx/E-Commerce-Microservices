package domain

import (
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// Order represents an order aggregate
type Order struct {
	ID              uuid.UUID       `db:"id"`
	UserID          uuid.UUID       `db:"user_id"`
	Status          OrderStatus     `db:"status"`
	TotalAmount     decimal.Decimal `db:"total_amount"`
	Currency        string          `db:"currency"`
	ShippingAddress string          `db:"shipping_address"`
	ShippingCost    decimal.Decimal `db:"shipping_cost"`
	TaxAmount       decimal.Decimal `db:"tax_amount"`
	Items           []OrderItem     `db:"-"`
	PaymentMethod   string          `db:"payment_method"`
	PaymentID       *uuid.UUID      `db:"payment_id"`
	ExpiresAt       *time.Time      `db:"expires_at"`
	ConfirmedAt     *time.Time      `db:"confirmed_at"`
	CancelledAt     *time.Time      `db:"cancelled_at"`
	CancelReason    string          `db:"cancel_reason"`
	CreatedAt       time.Time       `db:"created_at"`
	UpdatedAt       time.Time       `db:"updated_at"`
	Version         int             `db:"version"`
}

// OrderStatus state machine
type OrderStatus string

const (
	OrderStatusPending   OrderStatus = "PENDING"
	OrderStatusPaid      OrderStatus = "PAID"
	OrderStatusConfirmed OrderStatus = "CONFIRMED"
	OrderStatusShipped   OrderStatus = "SHIPPED"
	OrderStatusDelivered OrderStatus = "DELIVERED"
	OrderStatusCompleted OrderStatus = "COMPLETED"
	OrderStatusCancelled OrderStatus = "CANCELLED"
	OrderStatusRefunded  OrderStatus = "REFUNDED"
)

// ValidTransitions defines allowed state transitions
var ValidTransitions = map[OrderStatus][]OrderStatus{
	OrderStatusPending:   {OrderStatusPaid, OrderStatusCancelled},
	OrderStatusPaid:      {OrderStatusConfirmed, OrderStatusCancelled, OrderStatusRefunded},
	OrderStatusConfirmed: {OrderStatusShipped, OrderStatusCancelled},
	OrderStatusShipped:   {OrderStatusDelivered},
	OrderStatusDelivered: {OrderStatusCompleted},
	OrderStatusCompleted: {},
	OrderStatusCancelled: {},
	OrderStatusRefunded:  {},
}

func (s OrderStatus) CanTransitionTo(target OrderStatus) bool {
	allowed, ok := ValidTransitions[s]
	if !ok {
		return false
	}
	for _, a := range allowed {
		if a == target {
			return true
		}
	}
	return false
}

// OrderItem represents an item in an order
type OrderItem struct {
	ID            uuid.UUID       `db:"id"`
	OrderID       uuid.UUID       `db:"order_id"`
	ProductID     uuid.UUID       `db:"product_id"`
	ProductName   string          `db:"product_name"`
	ProductSKU    string          `db:"product_sku"`
	Quantity      int             `db:"quantity"`
	UnitPrice     decimal.Decimal `db:"unit_price"`
	Subtotal      decimal.Decimal `db:"subtotal"`
	ReservationID *uuid.UUID      `db:"reservation_id"`
	SellerID      uuid.UUID       `db:"seller_id"`
	CreatedAt     time.Time       `db:"created_at"`
}

// Cart represents user shopping cart
type Cart struct {
	ID        uuid.UUID   `db:"id"`
	UserID    uuid.UUID   `db:"user_id"`
	Items     []CartItem  `db:"-"`
	ExpiresAt time.Time   `db:"expires_at"`
	CreatedAt time.Time   `db:"created_at"`
	UpdatedAt time.Time   `db:"updated_at"`
}

type CartItem struct {
	ID         uuid.UUID       `db:"id"`
	CartID     uuid.UUID       `db:"cart_id"`
	ProductID  uuid.UUID       `db:"product_id"`
	Quantity   int             `db:"quantity"`
	UnitPrice  decimal.Decimal `db:"unit_price"`  // snapshot at add time
	ProductName string         `db:"product_name"`
	SellerID   uuid.UUID       `db:"seller_id"`
	Reserved   bool            `db:"reserved"`
	ReservationID *uuid.UUID   `db:"reservation_id"`
	CreatedAt  time.Time       `db:"created_at"`
	UpdatedAt  time.Time       `db:"updated_at"`
}
