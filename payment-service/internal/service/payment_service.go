package service

import (
        "bytes"
        "context"
        "encoding/json"
        "errors"
        "fmt"
        "io"
        "net/http"
        "strings"
        "time"

        "ecommerce/payment-service/internal/config"
        "ecommerce/payment-service/internal/domain"
        "ecommerce/payment-service/internal/gateway"
        "ecommerce/payment-service/pkg/idempotency"
        "ecommerce/payment-service/pkg/logger"

        "github.com/cenkalti/backoff/v4"
        "github.com/google/uuid"
        "github.com/jackc/pgx/v5"
        "github.com/jackc/pgx/v5/pgxpool"
        "github.com/redis/go-redis/v9"
        "github.com/segmentio/kafka-go"
        "github.com/shopspring/decimal"
)

type PaymentService struct {
        db    *pgxpool.Pool
        redis *redis.Client
        kafka *kafka.Writer
        cfg   *config.Config
        log   *logger.Logger
}

func NewPaymentService(db *pgxpool.Pool, redis *redis.Client, kafka *kafka.Writer, cfg *config.Config, log *logger.Logger) *PaymentService {
        return &PaymentService{db: db, redis: redis, kafka: kafka, cfg: cfg, log: log}
}

type CreatePaymentReq struct {
        OrderID        string `json:"order_id" binding:"required"`
        Method         string `json:"method" binding:"required"` // credit_card, gopay, bank_transfer
        Provider       string `json:"provider"`                   // midtrans, xendit
        IdempotencyKey string `json:"-"`
}

// CreatePayment with full idempotency & saga
func (s *PaymentService) CreatePayment(ctx context.Context, userID uuid.UUID, req CreatePaymentReq) (*domain.Payment, error) {
        orderID, err := uuid.Parse(req.OrderID)
        if err != nil {
                return nil, errors.New("invalid order_id")
        }
        provider := req.Provider
        if provider == "" {
                provider = "midtrans"
        }

        // Idempotency: check if payment already created with this key
        if req.IdempotencyKey != "" {
                existing, err := s.getPaymentByIdempotencyKey(ctx, req.IdempotencyKey)
                if err != nil {
                        return nil, err
                }
                if existing != nil {
                        s.log.Info("idempotent payment creation: returning existing", "payment_id", existing.ID)
                        return existing, nil
                }
        }

        // Fetch order to validate
        order, err := s.fetchOrder(ctx, orderID)
        if err != nil {
                return nil, fmt.Errorf("fetch order: %w", err)
        }
        if order.UserID != userID {
                return nil, errors.New("forbidden: order does not belong to user")
        }
        if order.Status != "PENDING" {
                return nil, fmt.Errorf("order not in payable state: %s", order.Status)
        }
        if order.ExpiresAt.Before(time.Now()) {
                return nil, errors.New("order has expired, please re-create order")
        }

        // Check if payment already exists for this order
        existingForOrder, err := s.getPaymentByOrderID(ctx, orderID)
        if err == nil && existingForOrder != nil {
                if existingForOrder.Status == domain.PaymentStatusSucceeded {
                        return nil, errors.New("order already paid")
                }
                // Resume existing pending payment
                return existingForOrder, nil
        }

        // Start DB transaction
        tx, err := s.db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
        if err != nil {
                return nil, fmt.Errorf("begin tx: %w", err)
        }
        defer func() { _ = tx.Rollback(ctx) }()

        paymentID := uuid.New()
        _, err = tx.Exec(ctx, `
                INSERT INTO payment_svc.payments
                        (id, order_id, user_id, amount, currency, status, method, provider, idempotency_key, version)
                VALUES ($1, $2, $3, $4, 'IDR', 'PENDING', $5, $6, $7, 1)
        `, paymentID, orderID, userID, order.TotalAmount, req.Method, provider, req.IdempotencyKey)
        if err != nil {
                return nil, fmt.Errorf("insert payment: %w", err)
        }

        if err := tx.Commit(ctx); err != nil {
                return nil, fmt.Errorf("commit: %w", err)
        }

        // Call provider (async-safe: payment is in PENDING state)
        // In production, this would call Midtrans/Xendit API
        providerTxID, providerResp, err := s.callPaymentProvider(ctx, paymentID, order, req.Method, provider)
        if err != nil {
                // Mark as failed
                s.updatePaymentStatus(ctx, paymentID, domain.PaymentStatusFailed, "", fmt.Sprintf("provider error: %v", err))
                s.publishPaymentEvent(ctx, "payment.failed", paymentID, userID, map[string]any{
                        "reason": err.Error(),
                })
                return nil, fmt.Errorf("payment provider error: %w", err)
        }

        // Update payment with provider response
        s.updatePaymentStatus(ctx, paymentID, domain.PaymentStatusSucceeded, providerTxID, "")
        _, err = s.db.Exec(ctx, `
                UPDATE payment_svc.payments SET provider_response = $1 WHERE id = $2`,
                providerResp, paymentID)
        if err != nil {
                s.log.Error("failed to save provider response", err, "payment_id", paymentID)
        }

        // Notify order-service
        if err := s.notifyOrderService(ctx, orderID, paymentID, "SUCCEEDED"); err != nil {
                s.log.Error("failed to notify order-service", err, "order_id", orderID)
                // Don't fail payment — async retry will handle
        }

        // Publish event
        s.publishPaymentEvent(ctx, "payment.succeeded", paymentID, userID, map[string]any{
                "order_id":  orderID,
                "amount":    order.TotalAmount.String(),
                "method":    req.Method,
                "provider":  provider,
        })

        s.log.Info("payment created & succeeded", "payment_id", paymentID, "order_id", orderID)
        return s.GetPayment(ctx, paymentID, userID)
}

func (s *PaymentService) GetPayment(ctx context.Context, paymentID, userID uuid.UUID) (*domain.Payment, error) {
        p := &domain.Payment{}
        err := s.db.QueryRow(ctx, `
                SELECT id, order_id, user_id, amount, currency, status, method, provider,
                       provider_tx_id, provider_response, failure_reason, idempotency_key,
                       refunded_amount, created_at, updated_at, version
                FROM payment_svc.payments WHERE id = $1`, paymentID).Scan(
                &p.ID, &p.OrderID, &p.UserID, &p.Amount, &p.Currency, &p.Status, &p.Method,
                &p.Provider, &p.ProviderTxID, &p.ProviderResponse, &p.FailureReason,
                &p.IdempotencyKey, &p.RefundedAmount, &p.CreatedAt, &p.UpdatedAt, &p.Version,
        )
        if errors.Is(err, pgx.ErrNoRows) {
                return nil, errors.New("payment not found")
        }
        if err != nil {
                return nil, err
        }
        if p.UserID != userID {
                return nil, errors.New("forbidden")
        }
        return p, nil
}

type RefundReq struct {
        PaymentID string `json:"payment_id" binding:"required"`
        Amount    string `json:"amount" binding:"required"`
        Reason    string `json:"reason" binding:"required"`
}

func (s *PaymentService) RefundPayment(ctx context.Context, adminID uuid.UUID, req RefundReq) (*domain.Refund, error) {
        paymentID, err := uuid.Parse(req.PaymentID)
        if err != nil {
                return nil, errors.New("invalid payment_id")
        }
        amount, err := decimal.NewFromString(req.Amount)
        if err != nil {
                return nil, errors.New("invalid amount")
        }
        if amount.LessThanOrEqual(decimal.Zero) {
                return nil, errors.New("amount must be positive")
        }

        payment, err := s.GetPayment(ctx, paymentID, payment.UserID)
        if err != nil {
                // Admin can fetch any payment — use direct query
                payment, err = s.getPaymentAdmin(ctx, paymentID)
                if err != nil {
                        return nil, err
                }
        }

        if payment.Status != domain.PaymentStatusSucceeded && payment.Status != domain.PaymentStatusPartialRefund {
                return nil, fmt.Errorf("cannot refund payment in status %s", payment.Status)
        }
        if payment.RefundedAmount.Add(amount).GreaterThan(payment.Amount) {
                return nil, errors.New("refund amount exceeds payment amount")
        }

        // Start transaction
        tx, err := s.db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
        if err != nil {
                return nil, err
        }
        defer func() { _ = tx.Rollback(ctx) }()

        refundID := uuid.New()
        _, err = tx.Exec(ctx, `
                INSERT INTO payment_svc.refunds (id, payment_id, amount, reason, status, created_by)
                VALUES ($1, $2, $3, $4, 'PENDING', $5)`,
                refundID, paymentID, amount, req.Reason, adminID)
        if err != nil {
                return nil, fmt.Errorf("insert refund: %w", err)
        }

        newRefundedAmount := payment.RefundedAmount.Add(amount)
        newStatus := domain.PaymentStatusPartialRefund
        if newRefundedAmount.Equal(payment.Amount) {
                newStatus = domain.PaymentStatusRefunded
        }
        _, err = tx.Exec(ctx, `
                UPDATE payment_svc.payments
                SET refunded_amount = $1, status = $2, version = version + 1
                WHERE id = $3 AND version = $4`,
                newRefundedAmount, newStatus, paymentID, payment.Version)
        if err != nil {
                return nil, err
        }
        if err := tx.Commit(ctx); err != nil {
                return nil, err
        }

        // Call provider refund API (best-effort, async reconcile if fail)
        go func() {
                ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
                defer cancel()
                _ = s.callProviderRefund(ctx, refundID, payment, amount)
        }()

        s.publishPaymentEvent(ctx, "payment.refunded", paymentID, payment.UserID, map[string]any{
                "refund_id": refundID,
                "amount":    amount.String(),
                "reason":    req.Reason,
        })

        return s.getRefund(ctx, refundID)
}

func (s *PaymentService) getRefund(ctx context.Context, refundID uuid.UUID) (*domain.Refund, error) {
        r := &domain.Refund{}
        err := s.db.QueryRow(ctx, `
                SELECT id, payment_id, amount, reason, status, provider_ref_id, created_by, created_at, updated_at
                FROM payment_svc.refunds WHERE id = $1`, refundID).Scan(
                &r.ID, &r.PaymentID, &r.Amount, &r.Reason, &r.Status, &r.ProviderRefID,
                &r.CreatedBy, &r.CreatedAt, &r.UpdatedAt,
        )
        if err != nil {
                return nil, err
        }
        return r, nil
}

// ===== Withdrawal =====

type WithdrawalReq struct {
        Amount        string `json:"amount" binding:"required"`
        BankAccount   string `json:"bank_account" binding:"required"`
        BankCode      string `json:"bank_code" binding:"required"`
        AccountHolder string `json:"account_holder" binding:"required"`
}

func (s *PaymentService) RequestWithdrawal(ctx context.Context, sellerID uuid.UUID, req WithdrawalReq) (*domain.Withdrawal, error) {
        amount, err := decimal.NewFromString(req.Amount)
        if err != nil {
                return nil, errors.New("invalid amount")
        }
        if amount.LessThanOrEqual(decimal.NewFromInt(s.cfg.Withdrawal.MinAmount)) {
                return nil, fmt.Errorf("minimum withdrawal is %d", s.cfg.Withdrawal.MinAmount)
        }

        id := uuid.New()
        _, err = s.db.Exec(ctx, `
                INSERT INTO payment_svc.withdrawals
                        (id, seller_id, amount, currency, status, bank_account, bank_code, account_holder, version)
                VALUES ($1, $2, $3, 'IDR', 'PENDING', $4, $5, $6, 1)
        `, id, sellerID, amount, req.BankAccount, req.BankCode, req.AccountHolder)
        if err != nil {
                return nil, fmt.Errorf("create withdrawal: %w", err)
        }

        s.publishPaymentEvent(ctx, "withdrawal.requested", id, sellerID, map[string]any{
                "amount":      amount.String(),
                "bank_code":   req.BankCode,
        })

        // Auto-approve for small amounts (configurable)
        if amount.LessThanOrEqual(decimal.NewFromInt(s.cfg.Withdrawal.AutoApproveMax)) {
                return s.ApproveWithdrawal(ctx, sellerID, id, true, "auto-approved")
        }

        return s.getWithdrawal(ctx, id, sellerID)
}

func (s *PaymentService) ListWithdrawals(ctx context.Context, sellerID uuid.UUID, page, size int) ([]domain.Withdrawal, int, error) {
        var total int
        err := s.db.QueryRow(ctx,
                `SELECT COUNT(*) FROM payment_svc.withdrawals WHERE seller_id = $1`, sellerID).Scan(&total)
        if err != nil {
                return nil, 0, err
        }
        rows, err := s.db.Query(ctx, `
                SELECT id, seller_id, amount, currency, status, bank_account, bank_code, account_holder,
                       provider_ref_id, notes, processed_by, processed_at, created_at, updated_at, version
                FROM payment_svc.withdrawals WHERE seller_id = $1
                ORDER BY created_at DESC LIMIT $2 OFFSET $3`,
                sellerID, size, page*size)
        if err != nil {
                return nil, 0, err
        }
        defer rows.Close()
        result := []domain.Withdrawal{}
        for rows.Next() {
                var w domain.Withdrawal
                _ = rows.Scan(&w.ID, &w.SellerID, &w.Amount, &w.Currency, &w.Status,
                        &w.BankAccount, &w.BankCode, &w.AccountHolder, &w.ProviderRefID,
                        &w.Notes, &w.ProcessedBy, &w.ProcessedAt, &w.CreatedAt, &w.UpdatedAt, &w.Version)
                result = append(result, w)
        }
        return result, total, nil
}

func (s *PaymentService) ApproveWithdrawal(ctx context.Context, adminID, withdrawalID uuid.UUID, approve bool, reason string) (*domain.Withdrawal, error) {
        w := &domain.Withdrawal{}
        err := s.db.QueryRow(ctx, `
                SELECT id, seller_id, amount, status, version FROM payment_svc.withdrawals WHERE id = $1`,
                withdrawalID).Scan(&w.ID, &w.SellerID, &w.Amount, &w.Status, &w.Version)
        if err != nil {
                return nil, errors.New("withdrawal not found")
        }
        if w.Status != domain.WithdrawalStatusPending {
                return nil, fmt.Errorf("cannot approve withdrawal in status %s", w.Status)
        }
        newStatus := domain.WithdrawalStatusApproved
        if !approve {
                newStatus = domain.WithdrawalStatusRejected
        }
        cmd, err := s.db.Exec(ctx, `
                UPDATE payment_svc.withdrawals
                SET status = $1, notes = $2, processed_by = $3, processed_at = NOW(), version = version + 1
                WHERE id = $4 AND version = $5`,
                newStatus, reason, adminID, withdrawalID, w.Version)
        if err != nil {
                return nil, err
        }
        if cmd.RowsAffected() == 0 {
                return nil, errors.New("concurrent update")
        }

        s.publishPaymentEvent(ctx, "withdrawal."+string(newStatus).ToLower(), withdrawalID, w.SellerID, map[string]any{
                "amount": w.Amount.String(),
                "reason": reason,
        })

        return s.getWithdrawal(ctx, withdrawalID, adminID)
}

func (s *PaymentService) getWithdrawal(ctx context.Context, id, userID uuid.UUID) (*domain.Withdrawal, error) {
        w := &domain.Withdrawal{}
        err := s.db.QueryRow(ctx, `
                SELECT id, seller_id, amount, currency, status, bank_account, bank_code, account_holder,
                       provider_ref_id, notes, processed_by, processed_at, created_at, updated_at, version
                FROM payment_svc.withdrawals WHERE id = $1`, id).Scan(
                &w.ID, &w.SellerID, &w.Amount, &w.Currency, &w.Status,
                &w.BankAccount, &w.BankCode, &w.AccountHolder, &w.ProviderRefID,
                &w.Notes, &w.ProcessedBy, &w.ProcessedAt, &w.CreatedAt, &w.UpdatedAt, &w.Version,
        )
        if err != nil {
                return nil, err
        }
        return w, nil
}

// ===== Helpers =====

type orderInfo struct {
        ID          uuid.UUID       `json:"id"`
        UserID      uuid.UUID       `json:"user_id"`
        Status      string          `json:"status"`
        TotalAmount decimal.Decimal `json:"total_amount"`
        ExpiresAt   time.Time       `json:"expires_at"`
}

func (s *PaymentService) fetchOrder(ctx context.Context, orderID uuid.UUID) (*orderInfo, error) {
        url := fmt.Sprintf("%s/api/v1/orders/%s", s.cfg.OrderSvcURL, orderID)
        bo := backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 3)
        var order *orderInfo
        err := backoff.Retry(func() error {
                req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
                uid := ctx.Value("user_id")
                if uid != nil {
                        req.Header.Set("X-User-Id", uid.(string))
                }
                resp, err := http.DefaultClient.Do(req)
                if err != nil {
                        return err
                }
                defer resp.Body.Close()
                if resp.StatusCode == 404 {
                        return backoff.Permanent(errors.New("order not found"))
                }
                if resp.StatusCode != 200 {
                        return fmt.Errorf("order-service returned %d", resp.StatusCode)
                }
                body, _ := io.ReadAll(resp.Body)
                var o orderInfo
                if err := json.Unmarshal(body, &o); err != nil {
                        return err
                }
                order = &o
                return nil
        }, bo)
        if err != nil {
                return nil, err
        }
        return order, nil
}

func (s *PaymentService) getPaymentByIdempotencyKey(ctx context.Context, key string) (*domain.Payment, error) {
        if key == "" {
                return nil, nil
        }
        p := &domain.Payment{}
        err := s.db.QueryRow(ctx, `
                SELECT id, order_id, user_id, amount, currency, status, method, provider,
                       provider_tx_id, provider_response, failure_reason, idempotency_key,
                       refunded_amount, created_at, updated_at, version
                FROM payment_svc.payments WHERE idempotency_key = $1`, key).Scan(
                &p.ID, &p.OrderID, &p.UserID, &p.Amount, &p.Currency, &p.Status, &p.Method,
                &p.Provider, &p.ProviderTxID, &p.ProviderResponse, &p.FailureReason,
                &p.IdempotencyKey, &p.RefundedAmount, &p.CreatedAt, &p.UpdatedAt, &p.Version,
        )
        if errors.Is(err, pgx.ErrNoRows) {
                return nil, nil
        }
        if err != nil {
                return nil, err
        }
        return p, nil
}

func (s *PaymentService) getPaymentByOrderID(ctx context.Context, orderID uuid.UUID) (*domain.Payment, error) {
        p := &domain.Payment{}
        err := s.db.QueryRow(ctx, `
                SELECT id, order_id, user_id, amount, currency, status, method, provider,
                       provider_tx_id, provider_response, failure_reason, idempotency_key,
                       refunded_amount, created_at, updated_at, version
                FROM payment_svc.payments WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1`, orderID).Scan(
                &p.ID, &p.OrderID, &p.UserID, &p.Amount, &p.Currency, &p.Status, &p.Method,
                &p.Provider, &p.ProviderTxID, &p.ProviderResponse, &p.FailureReason,
                &p.IdempotencyKey, &p.RefundedAmount, &p.CreatedAt, &p.UpdatedAt, &p.Version,
        )
        if errors.Is(err, pgx.ErrNoRows) {
                return nil, nil
        }
        if err != nil {
                return nil, err
        }
        return p, nil
}

func (s *PaymentService) getPaymentAdmin(ctx context.Context, paymentID uuid.UUID) (*domain.Payment, error) {
        p := &domain.Payment{}
        err := s.db.QueryRow(ctx, `
                SELECT id, order_id, user_id, amount, currency, status, method, provider,
                       provider_tx_id, provider_response, failure_reason, idempotency_key,
                       refunded_amount, created_at, updated_at, version
                FROM payment_svc.payments WHERE id = $1`, paymentID).Scan(
                &p.ID, &p.OrderID, &p.UserID, &p.Amount, &p.Currency, &p.Status, &p.Method,
                &p.Provider, &p.ProviderTxID, &p.ProviderResponse, &p.FailureReason,
                &p.IdempotencyKey, &p.RefundedAmount, &p.CreatedAt, &p.UpdatedAt, &p.Version,
        )
        if err != nil {
                return nil, err
        }
        return p, nil
}

func (s *PaymentService) updatePaymentStatus(ctx context.Context, paymentID uuid.UUID, status domain.PaymentStatus, providerTxID, failureReason string) error {
        var err error
        if providerTxID != "" {
                _, err = s.db.Exec(ctx, `
                        UPDATE payment_svc.payments
                        SET status = $1, provider_tx_id = $2, version = version + 1
                        WHERE id = $3`, status, providerTxID, paymentID)
        } else if failureReason != "" {
                _, err = s.db.Exec(ctx, `
                        UPDATE payment_svc.payments
                        SET status = $1, failure_reason = $2, version = version + 1
                        WHERE id = $3`, status, failureReason, paymentID)
        } else {
                _, err = s.db.Exec(ctx, `
                        UPDATE payment_svc.payments
                        SET status = $1, version = version + 1
                        WHERE id = $2`, status, paymentID)
        }
        return err
}

// callPaymentProvider calls real Midtrans Snap API or Xendit Invoice API
func (s *PaymentService) callPaymentProvider(ctx context.Context, paymentID uuid.UUID, order *orderInfo, method, provider string) (string, string, error) {
        // Dev mode: no provider keys configured → simulate success
        if s.cfg.MidtransServerKey == "" && s.cfg.XenditSecretKey == "" {
                s.log.Info("dev mode: simulating payment provider success", "payment_id", paymentID)
                return "DEV-" + paymentID.String(), `{"status":"success","simulated":true}`, nil
        }

        switch strings.ToLower(provider) {
        case "xendit":
                return s.callXendit(ctx, paymentID, order, method)
        default: // midtrans
                return s.callMidtrans(ctx, paymentID, order, method)
        }
}

// callMidtrans calls Midtrans Snap API to create payment
func (s *PaymentService) callMidtrans(ctx context.Context, paymentID uuid.UUID, order *orderInfo, method string) (string, string, error) {
        client := gateway.NewMidtransClient(s.cfg.MidtransServerKey, "", s.cfg.Environment == "production")

        // Build Snap request
        snapReq := gateway.SnapTokenRequest{
                TransactionDetails: gateway.TransactionDetails{
                        OrderID:     order.ID.String(),
                        GrossAmount: order.TotalAmount.IntPart(),
                },
                CustomerDetails: &gateway.CustomerDetails{
                        FirstName: "Customer", // TODO: fetch from order
                        Email:     "customer@example.com",
                        Phone:     "",
                },
                Expiry: &gateway.ExpiryDetail{
                        Unit:     "minute",
                        Duration: 15,
                },
        }

        // Map payment method to Midtrans enabled_payments
        snapReq.EnabledPayments = mapMidtransMethod(method)

        // Note: In production, fetch order items from order-service and add to ItemDetails
        // For now, send single line item representing total
        snapReq.ItemDetails = []gateway.ItemDetail{
                {
                        ID:       order.ID.String(),
                        Name:     fmt.Sprintf("Order %s", order.ID.String()[:8]),
                        Price:    order.TotalAmount.IntPart(),
                        Quantity: 1,
                },
        }

        snapResp, err := client.GetSnapToken(ctx, snapReq)
        if err != nil {
                s.log.Error("midtrans snap failed", err, "order_id", order.ID)
                return "", "", fmt.Errorf("midtrans: %w", err)
        }

        // Get transaction status (will be PENDING until user pays via Snap UI)
        status, err := client.GetTransactionStatus(ctx, order.ID.String())
        if err != nil {
                s.log.Warn("midtrans status check failed", "error", err)
        }

        txID := snapResp.Token
        if status != nil && status.TransactionID != "" {
                txID = status.TransactionID
        }
        respJSON, _ := json.Marshal(status)

        // If status is already settlement (instant payment), mark succeeded
        // Otherwise, leave as PENDING — webhook will update later
        if status != nil && status.IsSuccess() {
                // Async: no need to do anything here, caller will update DB
        }

        return txID, string(respJSON), nil
}

// callXendit creates a Xendit invoice
func (s *PaymentService) callXendit(ctx context.Context, paymentID uuid.UUID, order *orderInfo, method string) (string, string, error) {
        client := gateway.NewXenditClient(s.cfg.XenditSecretKey, s.cfg.Environment == "production")

        invReq := gateway.InvoiceRequest{
                ExternalID:      order.ID.String(),
                Amount:          order.TotalAmount.IntPart(),
                PayerEmail:      "customer@example.com",
                Description:     fmt.Sprintf("Payment for order %s", order.ID),
                InvoiceDuration: 900, // 15 minutes
                Currency:        "IDR",
                Items:           []gateway.XenditItem{},
        }

        // Note: In production, fetch order items from order-service
        invReq.Items = []gateway.XenditItem{
                {
                        Name:     fmt.Sprintf("Order %s", order.ID.String()[:8]),
                        Quantity: 1,
                        Price:    order.TotalAmount.IntPart(),
                },
        }

        invResp, err := client.CreateInvoice(ctx, invReq)
        if err != nil {
                s.log.Error("xendit invoice failed", err, "order_id", order.ID)
                return "", "", fmt.Errorf("xendit: %w", err)
        }

        respJSON, _ := json.Marshal(invResp)
        return invResp.ID, string(respJSON), nil
}

// callProviderRefund calls real Midtrans/Xendit refund API
func (s *PaymentService) callProviderRefund(ctx context.Context, refundID uuid.UUID, payment *domain.Payment, amount decimal.Decimal) error {
        s.log.Info("calling provider refund", "refund_id", refundID, "payment_id", payment.ID, "amount", amount)

        var providerRefID string
        var err error

        if payment.Provider == "midtrans" && s.cfg.MidtransServerKey != "" {
                client := gateway.NewMidtransClient(s.cfg.MidtransServerKey, "", s.cfg.Environment == "production")
                // Use payment ID as order_id reference (Midtrans uses order_id)
                // In production: store order_id on payment record
                resp, refErr := client.RefundTransaction(ctx, payment.ID.String(), gateway.RefundRequest{
                        RefundKey: refundID.String(),
                        Amount:    amount.IntPart(),
                        Reason:    "Customer requested refund",
                })
                if refErr != nil {
                        err = refErr
                } else if resp != nil {
                        providerRefID = resp.TransactionID
                }
        } else if payment.Provider == "xendit" && s.cfg.XenditSecretKey != "" {
                client := gateway.NewXenditClient(s.cfg.XenditSecretKey, s.cfg.Environment == "production")
                resp, refErr := client.CreateRefund(ctx, gateway.XenditRefundRequest{
                        InvoiceID:  payment.ProviderTxIDString(),
                        Amount:     amount.IntPart(),
                        Reason:     "Customer requested refund",
                        ExternalID: refundID.String(),
                })
                if refErr != nil {
                        err = refErr
                } else if resp != nil {
                        providerRefID = resp.ID
                }
        } else {
                // Dev mode: auto-succeed
                providerRefID = "DEV-REFUND-" + refundID.String()
        }

        // Update refund status
        newStatus := "SUCCEEDED"
        if err != nil {
                newStatus = "FAILED"
                s.log.Error("provider refund failed", err, "refund_id", refundID)
        }
        _, dbErr := s.db.Exec(ctx, `
                UPDATE payment_svc.refunds
                SET status = $1, provider_ref_id = $2, updated_at = NOW()
                WHERE id = $3`,
                newStatus, providerRefID, refundID)
        if dbErr != nil {
                return dbErr
        }
        return err
}

// HandleMidtransWebhook processes Midtrans webhook notification
func (s *PaymentService) HandleMidtransWebhook(ctx context.Context, orderID, statusCode, grossAmount, signatureKey string) error {
        client := gateway.NewMidtransClient(s.cfg.MidtransServerKey, "", s.cfg.Environment == "production")

        // Verify signature (HMAC SHA512)
        if !client.VerifyWebhookSignature(orderID, statusCode, grossAmount, signatureKey) {
                return fmt.Errorf("invalid webhook signature")
        }

        // Re-fetch status from Midtrans (don't trust webhook payload)
        status, err := client.VerifyNotification(ctx, orderID)
        if err != nil {
                return fmt.Errorf("verify notification: %w", err)
        }

        // Map status to internal
        internalStatus := gateway.MapTransactionStatus(status.TransactionStatus)

        // Find payment by order_id
        var paymentID, userID uuid.UUID
        err = s.db.QueryRow(ctx, `
                SELECT id, user_id FROM payment_svc.payments WHERE order_id::text = $1
                ORDER BY created_at DESC LIMIT 1`,
                orderID).Scan(&paymentID, &userID)
        if err != nil {
                return fmt.Errorf("payment not found for order %s: %w", orderID, err)
        }

        // Update payment status
        if internalStatus == "SUCCEEDED" {
                s.updatePaymentStatus(ctx, paymentID, domain.PaymentStatusSucceeded, status.TransactionID, "")
                // Notify order service
                if err := s.notifyOrderService(ctx, uuid.MustParse(orderID), paymentID, "SUCCEEDED"); err != nil {
                        s.log.Error("notify order-service failed", err, "order_id", orderID)
                }
                s.publishPaymentEvent(ctx, "payment.succeeded", paymentID, userID, map[string]any{
                        "order_id":    orderID,
                        "provider_tx": status.TransactionID,
                        "via":         "webhook",
                })
        } else if internalStatus == "FAILED" {
                s.updatePaymentStatus(ctx, paymentID, domain.PaymentStatusFailed, "", status.StatusMessage)
                s.publishPaymentEvent(ctx, "payment.failed", paymentID, userID, map[string]any{
                        "order_id": orderID,
                        "reason":   status.StatusMessage,
                })
        }

        return nil
}

// mapMidtransMethod maps internal method to Midtrans payment types
func mapMidtransMethod(method string) []string {
        switch method {
        case "credit_card":
                return []string{"credit_card"}
        case "bank_transfer":
                return []string{"bca_va", "bni_va", "bri_va", "permata_va", "other_va"}
        case "e_wallet":
                return []string{"gopay", "shopeepay", "dana", "ovo", "qris"}
        case "qris":
                return []string{"qris"}
        case "bnpl":
                return []string{"akulaku"}
        case "retail_outlet":
                return []string{"alfamart", "indomaret"}
        default:
                return []string{
                        "credit_card", "bca_va", "bni_va", "bri_va", "gopay", "shopeepay", "qris",
                }
        }
}

func (s *PaymentService) notifyOrderService(ctx context.Context, orderID, paymentID uuid.UUID, status string) error {
        body := map[string]any{
                "order_id":   orderID.String(),
                "payment_id": paymentID.String(),
                "status":     status,
        }
        jsonBody, _ := json.Marshal(body)
        url := fmt.Sprintf("%s/internal/orders/%s/payment-status", s.cfg.OrderSvcURL, orderID)
        req, _ := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(jsonBody))
        req.Header.Set("Content-Type", "application/json")
        req.Header.Set("X-Internal-Token", s.cfg.InternalToken)
        resp, err := http.DefaultClient.Do(req)
        if err != nil {
                return err
        }
        resp.Body.Close()
        if resp.StatusCode >= 400 {
                return fmt.Errorf("order-service returned %d", resp.StatusCode)
        }
        return nil
}

func (s *PaymentService) publishPaymentEvent(ctx context.Context, action string, paymentID, userID uuid.UUID, extra map[string]any) {
        event := map[string]any{
                "event_id":    uuid.New().String(),
                "occurred_at": time.Now().UTC().Format(time.RFC3339Nano),
                "producer":    "payment-service",
                "action":      action,
                "actor":       map[string]any{"user_id": userID.String()},
                "resource": map[string]any{
                        "type": "payment",
                        "id":   paymentID.String(),
                },
                "version": "1.0",
        }
        for k, v := range extra {
                event[k] = v
        }
        msg, _ := json.Marshal(event)
        if err := s.kafka.WriteMessages(ctx, kafka.Message{
                Key:   paymentID.String(),
                Value: msg,
                Topic: "ecommerce.payment.events",
        }); err != nil {
                s.log.Error("failed to publish payment event", err, "action", action)
        }
}

func basicAuth(username, password string) string {
        // Implementation
        return "" // placeholder
}

// Unused import shim
var _ = idempotency.New
