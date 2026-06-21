package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// XenditClient implements real Xendit API integration
// Docs: https://developers.xendit.co/api-reference/
type XenditClient struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
}

func NewXenditClient(apiKey string, isProduction bool) *XenditClient {
	baseURL := "https://api.xendit.co"
	if !isProduction {
		baseURL = "https://api.xendit.co" // Xendit doesn't have sandbox; uses different API key
	}
	return &XenditClient{
		apiKey:     apiKey,
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// InvoiceRequest for Xendit Invoice API
type InvoiceRequest struct {
	ExternalID        string             `json:"external_id"`
	Amount            int64              `json:"amount"`
	PayerEmail        string             `json:"payer_email,omitempty"`
	Description       string             `json:"description,omitempty"`
	InvoiceDuration   int64              `json:"invoice_duration,omitempty"` // seconds
	Items             []XenditItem       `json:"items,omitempty"`
	FixedPrice        bool               `json:"fixed_price"`
	SuccessRedirectURL string            `json:"success_redirect_url,omitempty"`
	FailureRedirectURL string            `json:"failure_redirect_url,omitempty"`
	Currency          string             `json:"currency,omitempty"` // IDR default
	PaymentMethods    []string           `json:"payment_methods,omitempty"`
	ShouldSendEmail   bool               `json:"should_send_email,omitempty"`
	Customer          *XenditCustomer    `json:"customer,omitempty"`
}

type XenditItem struct {
	Name     string `json:"name"`
	Quantity int    `json:"quantity"`
	Price    int64  `json:"price"`
	Category string `json:"category,omitempty"`
	URL      string `json:"url,omitempty"`
}

type XenditCustomer struct {
	GivenNames string `json:"given_names"`
	Email      string `json:"email"`
	Mobile     string `json:"mobile_number,omitempty"`
}

// InvoiceResponse dari Xendit
type InvoiceResponse struct {
	ID                string            `json:"id"`
	ExternalID        string            `json:"external_id"`
	UserID            string            `json:"user_id"`
	Status            string            `json:"status"` // PENDING, PAID, EXPIRED
	MerchantName      string            `json:"merchant_name"`
	MerchantProfileURL string           `json:"merchant_profile_website_url"`
	Amount            int64             `json:"amount"`
	InvoiceURL        string            `json:"invoice_url"`
	ExpiryDate        string            `json:"expiry_date"`
	AvailableBanks    []XenditBank      `json:"available_banks,omitempty"`
	AvailableEWallets []XenditEWallet   `json:"available_ewallets,omitempty"`
	AvailableRetail   []XenditRetail    `json:"available_retail_outlets,omitempty"`
	Items             []XenditItem      `json:"items,omitempty"`
	Currency          string            `json:"currency"`
	Created           string            `json:"created"`
	Updated           string            `json:"updated"`
	PaidAmount        int64             `json:"paid_amount"`
	PaidAt            string            `json:"paid_at"`
	PaymentMethod     string            `json:"payment_method"`
	PaymentChannel    string            `json:"payment_channel"`
	Email             string            `json:"payer_email"`
	Description       string            `json:"description"`
}

type XenditBank struct {
	Bank        string `json:"bank"`
	BankAccount string `json:"bank_account_number"`
}

type XenditEWallet struct {
	EWallet string `json:"ewallet_type"`
}

type XenditRetail struct {
	RetailOutletName string `json:"retail_outlet_name"`
	PaymentCode      string `json:"payment_code"`
	TransferAmount   int64  `json:"transfer_amount"`
}

// CreateInvoice creates a Xendit invoice
func (x *XenditClient) CreateInvoice(ctx context.Context, req InvoiceRequest) (*InvoiceResponse, error) {
	body, _ := json.Marshal(req)
	httpReq, _ := http.NewRequestWithContext(ctx, "POST", x.baseURL+"/v2/invoices", bytes.NewReader(body))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.SetBasicAuth(x.apiKey, "")

	resp, err := x.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("xendit invoice request: %w", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return nil, fmt.Errorf("xendit invoice failed: status=%d body=%s", resp.StatusCode, respBody)
	}

	var invResp InvoiceResponse
	if err := json.Unmarshal(respBody, &invResp); err != nil {
		return nil, fmt.Errorf("decode invoice response: %w", err)
	}
	return &invResp, nil
}

// GetInvoice retrieves invoice by ID
func (x *XenditClient) GetInvoice(ctx context.Context, invoiceID string) (*InvoiceResponse, error) {
	url := fmt.Sprintf("%s/v2/invoices/%s", x.baseURL, invoiceID)
	httpReq, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	httpReq.SetBasicAuth(x.apiKey, "")

	resp, err := x.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var invResp InvoiceResponse
	if err := json.Unmarshal(respBody, &invResp); err != nil {
		return nil, err
	}
	return &invResp, nil
}

// RefundRequest for Xendit refund
type XenditRefundRequest struct {
	InvoiceID    string `json:"invoice_id"`
	Amount       int64  `json:"amount"`
	Reason       string `json:"reason"`
	ExternalID   string `json:"external_id,omitempty"`
}

type XenditRefundResponse struct {
	ID          string `json:"id"`
	InvoiceID   string `json:"invoice_id"`
	Amount      int64  `json:"amount"`
	Reason      string `json:"reason"`
	Status      string `json:"status"` // PENDING, COMPLETED, FAILED
	ExternalID  string `json:"external_id"`
	Created     string `json:"created"`
	Updated     string `json:"updated"`
}

// CreateRefund issues a refund for a paid invoice
func (x *XenditClient) CreateRefund(ctx context.Context, req XenditRefundRequest) (*XenditRefundResponse, error) {
	body, _ := json.Marshal(req)
	httpReq, _ := http.NewRequestWithContext(ctx, "POST", x.baseURL+"/payment/xendit/invoice/refund", bytes.NewReader(body))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.SetBasicAuth(x.apiKey, "")

	resp, err := x.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var refundResp XenditRefundResponse
	if err := json.Unmarshal(respBody, &refundResp); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return &refundResp, fmt.Errorf("xendit refund failed (status=%d)", resp.StatusCode)
	}
	return &refundResp, nil
}

// VerifyWebhookToken verifies Xendit webhook token
// Xendit sends `X-CALLBACK-TOKEN` header that must match your webhook verification token
func (x *XenditClient) VerifyWebhookToken(receivedToken, expectedToken string) bool {
	if expectedToken == "" {
		return false
	}
	return receivedToken == expectedToken
}

// MapInvoiceStatus maps Xendit invoice status to internal PaymentStatus
func MapInvoiceStatus(xenditStatus string) string {
	switch xenditStatus {
	case "PAID":
		return "SUCCEEDED"
	case "PENDING":
		return "PENDING"
	case "EXPIRED":
		return "FAILED"
	default:
		return "PENDING"
	}
}
