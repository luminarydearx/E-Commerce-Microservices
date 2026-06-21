package handler

import (
	"testing"
)

func TestContains(t *testing.T) {
	tests := []struct {
		s, sub string
		want   bool
	}{
		{"admin,superadmin", "admin", true},
		{"admin,superadmin", "superadmin", true},
		{"buyer,seller", "admin", false},
		{"", "admin", false},
		{"admin", "", false},
		{"admin,seller", "buyer", false},
	}

	for _, tt := range tests {
		got := contains(tt.s, tt.sub)
		if got != tt.want {
			t.Errorf("contains(%q, %q) = %v, want %v", tt.s, tt.sub, got, tt.want)
		}
	}
}

func TestAdminOnlyLogic(t *testing.T) {
	// Simulate AdminOnly check
	checkAdmin := func(roles string) bool {
		return contains(roles, "admin") || contains(roles, "superadmin")
	}

	if !checkAdmin("admin,buyer") {
		t.Error("admin role should pass")
	}
	if !checkAdmin("superadmin") {
		t.Error("superadmin role should pass")
	}
	if checkAdmin("buyer,seller") {
		t.Error("buyer/seller should fail")
	}
	if checkAdmin("") {
		t.Error("empty roles should fail")
	}
}
