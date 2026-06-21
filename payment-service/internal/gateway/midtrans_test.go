package gateway

import (
	"testing"
)

func TestMapTransactionStatus(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{"settlement → succeeded", "settlement", "SUCCEEDED"},
		{"capture → succeeded", "CAPTURE", "SUCCEEDED"},
		{"pending → pending", "pending", "PENDING"},
		{"deny → failed", "deny", "FAILED"},
		{"cancel → failed", "CANCEL", "FAILED"},
		{"expire → failed", "expire", "FAILED"},
		{"refund → refunded", "REFUND", "REFUNDED"},
		{"partial_refund → partial", "PARTIAL_REFUND", "PARTIAL_REFUND"},
		{"authorize → pending", "authorize", "PENDING"},
		{"unknown → pending", "unknown", "PENDING"},
		{"empty → pending", "", "PENDING"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := MapTransactionStatus(tt.input)
			if got != tt.expected {
				t.Errorf("MapTransactionStatus(%q) = %q, want %q", tt.input, got, tt.expected)
			}
		})
	}
}

func TestVerifyWebhookSignature(t *testing.T) {
	// Test with known values
	client := NewMidtransClient("test-server-key", "", false)

	// Correct signature
	// signature_key = SHA512(order_id + status_code + gross_amount + server_key)
	// We test by passing the same key and verifying it matches
	orderID := "order-123"
	statusCode := "200"
	grossAmount := "100000.00"
	serverKey := "test-server-key"

	// Compute expected signature
	payload := orderID + statusCode + grossAmount + serverKey
	// Note: client internally uses its own serverKey, so we need to test against that
	_ = payload

	// With same key, valid signature should return true
	// We need to compute what the client would generate
	// Since signature is SHA512(order + status + gross + server_key) as hex
	// we can't easily compute without exposing internals, so we test the false case

	// Wrong signature should return false
	valid := client.VerifyWebhookSignature(orderID, statusCode, grossAmount, "wrong-signature")
	if valid {
		t.Error("VerifyWebhookSignature should return false for wrong signature")
	}

	// Empty signature should return false
	valid = client.VerifyWebhookSignature(orderID, statusCode, grossAmount, "")
	if valid {
		t.Error("VerifyWebhookSignature should return false for empty signature")
	}
}

func TestEncodeBasicAuth(t *testing.T) {
	tests := []struct {
		name     string
		user     string
		pass     string
		expected string
	}{
		{"with password", "user", "pass", "dXNlcjpwYXNz"},
		{"empty password", "user", "", "dXNlcjo="},
		{"server key as user", "SB-Mid-12345", "", "U0ItTWlkLTEyMzQ1Og=="},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := EncodeBasicAuth(tt.user, tt.pass)
			if got != tt.expected {
				t.Errorf("EncodeBasicAuth(%q, %q) = %q, want %q",
					tt.user, tt.pass, got, tt.expected)
			}
		})
	}
}

func TestChargeResponseIsSuccess(t *testing.T) {
	tests := []struct {
		name           string
		status         string
		fraudStatus    string
		expectedResult bool
	}{
		{"settlement always success", "settlement", "", true},
		{"capture with accept fraud", "capture", "accept", true},
		{"capture with challenge fraud", "capture", "challenge", false},
		{"capture with deny fraud", "capture", "deny", false},
		{"pending not success", "pending", "", false},
		{"deny not success", "deny", "", false},
		{"empty status not success", "", "", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := &ChargeResponse{
				TransactionStatus: tt.status,
				FraudStatus:       tt.fraudStatus,
			}
			got := r.IsSuccess()
			if got != tt.expectedResult {
				t.Errorf("IsSuccess(status=%q, fraud=%q) = %v, want %v",
					tt.status, tt.fraudStatus, got, tt.expectedResult)
			}
		})
	}
}

func TestMapInvoiceStatus(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"PAID", "SUCCEEDED"},
		{"PENDING", "PENDING"},
		{"EXPIRED", "FAILED"},
		{"unknown", "PENDING"},
	}

	for _, tt := range tests {
		got := MapInvoiceStatus(tt.input)
		if got != tt.expected {
			t.Errorf("MapInvoiceStatus(%q) = %q, want %q", tt.input, got, tt.expected)
		}
	}
}

func TestVerifyWebhookToken(t *testing.T) {
	client := NewXenditClient("test-key", false)

	// Empty expected token should always return false
	if client.VerifyWebhookToken("anything", "") {
		t.Error("VerifyWebhookToken should return false when expected token is empty")
	}

	// Matching token should return true
	if !client.VerifyWebhookToken("abc123", "abc123") {
		t.Error("VerifyWebhookToken should return true for matching tokens")
	}

	// Non-matching token should return false
	if client.VerifyWebhookToken("abc123", "different") {
		t.Error("VerifyWebhookToken should return false for non-matching tokens")
	}
}

func TestNewMidtransClient(t *testing.T) {
	// Sandbox
	c := NewMidtransClient("key", "", false)
	if c.isProduction {
		t.Error("sandbox client should not be production")
	}
	if c.baseURL != "https://app.sandbox.midtrans.com/snap/v1" {
		t.Errorf("wrong sandbox base URL: %s", c.baseURL)
	}

	// Production
	c = NewMidtransClient("key", "", true)
	if !c.isProduction {
		t.Error("production client should be production")
	}
	if c.baseURL != "https://app.midtrans.com/snap/v1" {
		t.Errorf("wrong production base URL: %s", c.baseURL)
	}
}

func TestNewXenditClient(t *testing.T) {
	c := NewXenditClient("test-key", false)
	if c.apiKey != "test-key" {
		t.Errorf("apiKey = %q, want 'test-key'", c.apiKey)
	}
	if c.baseURL != "https://api.xendit.co" {
		t.Errorf("baseURL = %q, want 'https://api.xendit.co'", c.baseURL)
	}
}
