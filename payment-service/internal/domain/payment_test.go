package domain

import "testing"

func TestPaymentStatusCanTransitionTo(t *testing.T) {
	tests := []struct {
		name     string
		from     PaymentStatus
		to       PaymentStatus
		expected bool
	}{
		{"pending to succeeded", PaymentStatusPending, PaymentStatusSucceeded, true},
		{"pending to failed", PaymentStatusPending, PaymentStatusFailed, true},
		{"pending to refunded (invalid)", PaymentStatusPending, PaymentStatusRefunded, false},
		{"succeeded to refunded", PaymentStatusSucceeded, PaymentStatusRefunded, true},
		{"succeeded to partial_refund", PaymentStatusSucceeded, PaymentStatusPartialRefund, true},
		{"succeeded to pending (invalid)", PaymentStatusSucceeded, PaymentStatusPending, false},
		{"failed to anything (terminal)", PaymentStatusFailed, PaymentStatusSucceeded, false},
		{"failed to pending (invalid)", PaymentStatusFailed, PaymentStatusPending, false},
		{"refunded to anything (terminal)", PaymentStatusRefunded, PaymentStatusSucceeded, false},
		{"partial_refund to refunded", PaymentStatusPartialRefund, PaymentStatusRefunded, true},
		{"partial_refund to pending (invalid)", PaymentStatusPartialRefund, PaymentStatusPending, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.from.CanTransitionTo(tt.to)
			if got != tt.expected {
				t.Errorf("%v.CanTransitionTo(%v) = %v, want %v",
					tt.from, tt.to, got, tt.expected)
			}
		})
	}
}

func TestProviderTxIDString(t *testing.T) {
	tests := []struct {
		name     string
		txID     *string
		expected string
	}{
		{"nil", nil, ""},
		{"empty string", strPtr(""), ""},
		{"valid id", strPtr("tx-123"), "tx-123"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := &Payment{ProviderTxID: tt.txID}
			got := p.ProviderTxIDString()
			if got != tt.expected {
				t.Errorf("ProviderTxIDString() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func strPtr(s string) *string {
	return &s
}
