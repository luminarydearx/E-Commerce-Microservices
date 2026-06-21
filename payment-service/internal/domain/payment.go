package domain

import (
        "time"

        "github.com/google/uuid"
        "github.com/shopspring/decimal"
)

type Payment struct {
        ID               uuid.UUID       `db:"id"`
        OrderID          uuid.UUID       `db:"order_id"`
        UserID           uuid.UUID       `db:"user_id"`
        Amount           decimal.Decimal `db:"amount"`
        Currency         string          `db:"currency"`
        Status           PaymentStatus   `db:"status"`
        Method           string          `db:"method"`
        Provider         string          `db:"provider"` // midtrans, xendit
        ProviderTxID     *string         `db:"provider_tx_id"`
        ProviderResponse string          `db:"provider_response"`
        FailureReason    *string         `db:"failure_reason"`
        IdempotencyKey   string          `db:"idempotency_key"`
        RefundedAmount   decimal.Decimal `db:"refunded_amount"`
        CreatedAt        time.Time       `db:"created_at"`
        UpdatedAt        time.Time       `db:"updated_at"`
        Version          int             `db:"version"`
}

type PaymentStatus string

const (
        PaymentStatusPending   PaymentStatus = "PENDING"
        PaymentStatusSucceeded PaymentStatus = "SUCCEEDED"
        PaymentStatusFailed    PaymentStatus = "FAILED"
        PaymentStatusRefunded  PaymentStatus = "REFUNDED"
        PaymentStatusPartialRefund PaymentStatus = "PARTIAL_REFUND"
)

var ValidPaymentTransitions = map[PaymentStatus][]PaymentStatus{
        PaymentStatusPending:        {PaymentStatusSucceeded, PaymentStatusFailed},
        PaymentStatusSucceeded:      {PaymentStatusRefunded, PaymentStatusPartialRefund},
        PaymentStatusFailed:         {},
        PaymentStatusRefunded:       {},
        PaymentStatusPartialRefund:  {PaymentStatusRefunded},
}

func (s PaymentStatus) CanTransitionTo(target PaymentStatus) bool {
        allowed, ok := ValidPaymentTransitions[s]
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

type Refund struct {
        ID          uuid.UUID       `db:"id"`
        PaymentID   uuid.UUID       `db:"payment_id"`
        Amount      decimal.Decimal `db:"amount"`
        Reason      string          `db:"reason"`
        Status      RefundStatus    `db:"status"`
        ProviderRefID *string       `db:"provider_ref_id"`
        CreatedBy   uuid.UUID       `db:"created_by"`
        CreatedAt   time.Time       `db:"created_at"`
        UpdatedAt   time.Time       `db:"updated_at"`
}

type RefundStatus string

const (
        RefundStatusPending   RefundStatus = "PENDING"
        RefundStatusSucceeded RefundStatus = "SUCCEEDED"
        RefundStatusFailed    RefundStatus = "FAILED"
)

type Withdrawal struct {
        ID            uuid.UUID       `db:"id"`
        SellerID      uuid.UUID       `db:"seller_id"`
        Amount        decimal.Decimal `db:"amount"`
        Currency      string          `db:"currency"`
        Status        WithdrawalStatus `db:"status"`
        BankAccount   string          `db:"bank_account"`
        BankCode      string          `db:"bank_code"`
        AccountHolder string          `db:"account_holder"`
        ProviderRefID *string         `db:"provider_ref_id"`
        Notes         string          `db:"notes"`
        ProcessedBy   *uuid.UUID      `db:"processed_by"`
        ProcessedAt   *time.Time      `db:"processed_at"`
        CreatedAt     time.Time       `db:"created_at"`
        UpdatedAt     time.Time       `db:"updated_at"`
        Version       int             `db:"version"`
}

type WithdrawalStatus string

const (
        WithdrawalStatusPending  WithdrawalStatus = "PENDING"
        WithdrawalStatusApproved WithdrawalStatus = "APPROVED"
        WithdrawalStatusRejected WithdrawalStatus = "REJECTED"
        WithdrawalStatusPaid     WithdrawalStatus = "PAID"
        WithdrawalStatusFailed   WithdrawalStatus = "FAILED"
)

// ProviderTxIDString returns provider transaction ID as string (safe for nil)
func (p *Payment) ProviderTxIDString() string {
        if p.ProviderTxID == nil {
                return ""
        }
        return *p.ProviderTxID
}
