package gateway

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha512"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// MidtransClient implements real Midtrans Snap API integration
// Docs: https://snap-docs.midtrans.com/
type MidtransClient struct {
	serverKey     string
	clientKey     string
	baseURL       string // https://app.sandbox.midtrans.com/snap/v1 or production
	apiURL        string // https://api.sandbox.midtrans.com/v2 or production
	isProduction  bool
	httpClient    *http.Client
}

func NewMidtransClient(serverKey, clientKey string, isProduction bool) *MidtransClient {
	baseURL := "https://app.sandbox.midtrans.com/snap/v1"
	apiURL := "https://api.sandbox.midtrans.com/v2"
	if isProduction {
		baseURL = "https://app.midtrans.com/snap/v1"
		apiURL = "https://api.midtrans.com/v2"
	}
	return &MidtransClient{
		serverKey:    serverKey,
		clientKey:    clientKey,
		baseURL:      baseURL,
		apiURL:       apiURL,
		isProduction: isProduction,
		httpClient:   &http.Client{Timeout: 30 * time.Second},
	}
}

// SnapTokenRequest for /snap/v1/transactions
type SnapTokenRequest struct {
	TransactionDetails TransactionDetails `json:"transaction_details"`
	ItemDetails        []ItemDetail       `json:"item_details,omitempty"`
	CustomerDetails    *CustomerDetails   `json:"customer_details,omitempty"`
	EnabledPayments    []string           `json:"enabled_payments,omitempty"`
	Expiry             *ExpiryDetail      `json:"expiry,omitempty"`
	CreditCard         *CreditCardDetail  `json:"credit_card,omitempty"`
	Callbacks          *Callbacks         `json:"callbacks,omitempty"`
	Shipment           *ShipmentDetail    `json:"shipment,omitempty"`
}

type TransactionDetails struct {
	OrderID     string `json:"order_id"`
	GrossAmount int64  `json:"gross_amount"`
}

type ItemDetail struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Price    int64  `json:"price"`
	Quantity int    `json:"quantity"`
	Brand    string `json:"brand,omitempty"`
	Category string `json:"category,omitempty"`
	Merchant string `json:"merchant_name,omitempty"`
}

type CustomerDetails struct {
	FirstName    string `json:"first_name"`
	LastName     string `json:"last_name,omitempty"`
	Email        string `json:"email,omitempty"`
	Phone        string `json:"phone,omitempty"`
	BillingAddr  *Address `json:"billing_address,omitempty"`
	ShippingAddr *Address `json:"shipping_address,omitempty"`
}

type Address struct {
	FirstName   string `json:"first_name"`
	LastName    string `json:"last_name,omitempty"`
	Phone       string `json:"phone,omitempty"`
	Address     string `json:"address"`
	City        string `json:"city"`
	PostalCode  string `json:"postal_code"`
	CountryCode string `json:"country_code,omitempty"`
}

type ExpiryDetail struct {
	StartTime string `json:"start_time,omitempty"` // ISO 8601
	Unit      string `json:"unit"`                 // minute, hour, day
	Duration  int    `json:"duration"`
}

type CreditCardDetail struct {
	Secure        bool     `json:"secure,omitempty"`
	Bank          string   `json:"bank,omitempty"`
	Installment   *bool    `json:"installment,omitempty"`
	Terminal      string   `json:"terminal,omitempty"`
	Channel       string   `json:"channel,omitempty"`
	WhiteListBin  []string `json:"whitelist_bins,omitempty"`
}

type Callbacks struct {
	Finish string `json:"finish,omitempty"`
}

type ShipmentDetail struct {
	TrackingNumber string `json:"tracking_number,omitempty"`
}

// SnapTokenResponse dari Midtrans Snap
type SnapTokenResponse struct {
	Token       string `json:"token"`
	RedirectURL string `json:"redirect_url"`
}

// ChargeResponse dari /v2/{order_id}/charge atau status
type ChargeResponse struct {
	StatusCode        string         `json:"status_code"`
	StatusMessage     string         `json:"status_message"`
	TransactionID     string         `json:"transaction_id"`
	OrderID           string         `json:"order_id"`
	GrossAmount       string         `json:"gross_amount"`
	PaymentType       string         `json:"payment_type"`
	TransactionTime   string         `json:"transaction_time"`
	TransactionStatus string         `json:"transaction_status"` // authorize, capture, settlement, deny, pending, cancel, expire, failure, refund, partial_refund
	FraudStatus       string         `json:"fraud_status"`       // accept, challenge, deny
	Store             string         `json:"store,omitempty"`
	SettlementTime    string         `json:"settlement_time,omitempty"`
	ApprovalCode      string         `json:"approval_code,omitempty"`
	PermataVaNumber   string         `json:"permata_va_number,omitempty"`
	VaNumbers         []VaNumber     `json:"va_numbers,omitempty"`
	BillKey           string         `json:"bill_key,omitempty"`
	BillerCode        string         `json:"biller_code,omitempty"`
	QrString          string         `json:"qr_string,omitempty"`
	Actions           []ActionLink   `json:"actions,omitempty"`
	Refunds           []RefundDetail `json:"refunds,omitempty"`
}

type VaNumber struct {
	Bank     string `json:"bank"`
	VaNumber string `json:"va_number"`
}

type ActionLink struct {
	Name string `json:"name"`
	URL  string `json:"url"`
}

type RefundDetail struct {
	RefundChargebackID string `json:"refund_chargeback_id"`
	RefundAmount       string `json:"refund_amount"`
	Reason             string `json:"reason"`
	RefundKey          string `json:"refund_key,omitempty"`
	Status             string `json:"status"`
	CreatedAt          string `json:"created_at"`
}

// RefundRequest untuk /v2/{order_id}/refund
type RefundRequest struct {
	RefundKey  string `json:"refund_key,omitempty"`
	Amount     int64  `json:"amount"`
	Reason     string `json:"reason"`
}

// GetSnapToken creates a Snap token for frontend payment
func (m *MidtransClient) GetSnapToken(ctx context.Context, req SnapTokenRequest) (*SnapTokenResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal snap request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", m.baseURL+"/transactions", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json")
	httpReq.SetBasicAuth(m.serverKey, "")

	resp, err := m.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("midtrans snap request: %w", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusCreated {
		return nil, fmt.Errorf("midtrans snap failed: status=%d body=%s", resp.StatusCode, respBody)
	}

	var snapResp SnapTokenResponse
	if err := json.Unmarshal(respBody, &snapResp); err != nil {
		return nil, fmt.Errorf("decode snap response: %w", err)
	}
	return &snapResp, nil
}

// ChargeTransaction direct charge (server-to-server, no Snap UI)
func (m *MidtransClient) ChargeTransaction(ctx context.Context, orderID string, payload map[string]interface{}) (*ChargeResponse, error) {
	body, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/%s/charge", m.apiURL, orderID)

	httpReq, _ := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json")
	httpReq.SetBasicAuth(m.serverKey, "")

	resp, err := m.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var chargeResp ChargeResponse
	if err := json.Unmarshal(respBody, &chargeResp); err != nil {
		return nil, fmt.Errorf("decode charge response: %w (body: %s)", err, respBody)
	}
	if resp.StatusCode >= 400 {
		return &chargeResp, fmt.Errorf("midtrans charge failed: %s (status=%d)", chargeResp.StatusMessage, resp.StatusCode)
	}
	return &chargeResp, nil
}

// GetTransactionStatus checks transaction status from Midtrans
func (m *MidtransClient) GetTransactionStatus(ctx context.Context, orderID string) (*ChargeResponse, error) {
	url := fmt.Sprintf("%s/%s/status", m.apiURL, orderID)
	httpReq, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	httpReq.Header.Set("Accept", "application/json")
	httpReq.SetBasicAuth(m.serverKey, "")

	resp, err := m.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var statusResp ChargeResponse
	if err := json.Unmarshal(respBody, &statusResp); err != nil {
		return nil, fmt.Errorf("decode status response: %w", err)
	}
	return &statusResp, nil
}

// RefundTransaction issues a refund for a settled transaction
func (m *MidtransClient) RefundTransaction(ctx context.Context, orderID string, req RefundRequest) (*ChargeResponse, error) {
	body, _ := json.Marshal(req)
	url := fmt.Sprintf("%s/%s/refund", m.apiURL, orderID)

	httpReq, _ := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json")
	httpReq.SetBasicAuth(m.serverKey, "")

	resp, err := m.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var refundResp ChargeResponse
	if err := json.Unmarshal(respBody, &refundResp); err != nil {
		return nil, fmt.Errorf("decode refund response: %w (body: %s)", err, respBody)
	}
	if resp.StatusCode >= 400 {
		return &refundResp, fmt.Errorf("midtrans refund failed: %s (status=%d)", refundResp.StatusMessage, resp.StatusCode)
	}
	return &refundResp, nil
}

// CancelTransaction cancels a pending transaction
func (m *MidtransClient) CancelTransaction(ctx context.Context, orderID string) (*ChargeResponse, error) {
	url := fmt.Sprintf("%s/%s/cancel", m.apiURL, orderID)
	httpReq, _ := http.NewRequestWithContext(ctx, "POST", url, nil)
	httpReq.Header.Set("Accept", "application/json")
	httpReq.SetBasicAuth(m.serverKey, "")

	resp, err := m.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var cancelResp ChargeResponse
	if err := json.Unmarshal(respBody, &cancelResp); err != nil {
		return nil, err
	}
	return &cancelResp, nil
}

// VerifyWebhookSignature verifies Midtrans webhook signature
// Midtrans sends signature_key = SHA512(order_id + status_code + gross_amount + server_key)
func (m *MidtransClient) VerifyWebhookSignature(orderID, statusCode, grossAmount, signatureKey string) bool {
	payload := orderID + statusCode + grossAmount + m.serverKey
	h := hmac.New(sha512.New, []byte(m.serverKey))
	// Midtrans uses lowercase hex of SHA512
	h.Write([]byte(payload))
	expected := fmt.Sprintf("%x", h.Sum(nil))
	return hmac.Equal([]byte(expected), []byte(signatureKey))
}

// VerifyNotification verifies and parses Midtrans webhook notification
func (m *MidtransClient) VerifyNotification(ctx context.Context, orderID string) (*ChargeResponse, error) {
	// Always re-fetch status from Midtrans API (don't trust webhook payload)
	return m.GetTransactionStatus(ctx, orderID)
}

// MapTransactionStatus maps Midtrans status to internal PaymentStatus
func MapTransactionStatus(midtransStatus string) string {
	switch strings.ToUpper(midtransStatus) {
	case "CAPTURE", "SETTLEMENT":
		return "SUCCEEDED"
	case "PENDING":
		return "PENDING"
	case "DENY", "CANCEL", "EXPIRE", "FAILURE":
		return "FAILED"
	case "REFUND":
		return "REFUNDED"
	case "PARTIAL_REFUND":
		return "PARTIAL_REFUND"
	case "AUTHORIZE":
		return "PENDING" // need capture
	default:
		return "PENDING"
	}
}

// IsSuccess returns true if transaction is considered successful
func (r *ChargeResponse) IsSuccess() bool {
	status := strings.ToUpper(r.TransactionStatus)
	return status == "SETTLEMENT" || (status == "CAPTURE" && strings.ToUpper(r.FraudStatus) == "ACCEPT")
}

// EncodeBasicAuth returns base64-encoded Basic auth header value
func EncodeBasicAuth(username, password string) string {
	return base64.StdEncoding.EncodeToString([]byte(username + ":" + password))
}
